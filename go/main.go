package main

import (
	"context"
	"fmt"
	"log"
	"math/rand"
	"net"
	"os"
	"sync"
	"time"

	"google.golang.org/grpc"
	pb "path/to/raft" // You'll need to generate this from your protobuf
)

const (
	port               = 50051
	heartbeatTimeout   = 10 * time.Millisecond
	electionTimeoutMin = 15 * time.Millisecond
	electionTimeoutMax = 30 * time.Millisecond
)

type nodeState int

const (
	follower nodeState = iota
	candidate
	leader
)

func (s nodeState) String() string {
	switch s {
	case follower:
		return "FOLLOWER"
	case candidate:
		return "CANDIDATE"
	case leader:
		return "LEADER"
	default:
		return "UNKNOWN"
	}
}

type RaftServer struct {
	pb.UnimplementedRaftServer
	mu sync.Mutex

	numberOfNodes int
	state        nodeState
	term         int64
	commitIndex  int64 // equivalent to 'c' in Python version
	nodeId       string
	votedFor     string
	logs         []*pb.Log
	database     map[string]string
	otherNodes   []struct {
		id   string
		addr string
	}
	lastHeartbeat time.Time
	electionTimer *time.Timer
	leaderId      string
	running       bool
}

func sendReport(sender, receiver, rpcType, action string) {
	conn, err := grpc.Dial("reporter:50052", grpc.WithInsecure())
	if err != nil {
		log.Printf("Failed to connect to reporter: %v", err)
		return
	}
	defer conn.Close()

	client := pb.NewReportClient(conn)
	timestamp := time.Now().Format("15:04:05.000")

	_, err = client.SendReport(context.Background(), &pb.ReportRequest{
		TimeStamp: timestamp,
		RpcType:   rpcType,
		Sender:    sender,
		Receiver:  receiver,
		Action:    action,
	})

	if err != nil {
		log.Printf("Failed to send report: %v", err)
	}
}

func NewRaftServer() *RaftServer {
	hostname, _ := os.Hostname()
	
	s := &RaftServer{
		numberOfNodes: 5,
		state:        follower,
		term:         0,
		commitIndex:  -1,
		nodeId:       hostname,
		database:     make(map[string]string),
		running:      true,
	}

	// Initialize other nodes
	allNodes := []struct {
		id   string
		addr string
	}{
		{"node1", "node1:50051"},
		{"node2", "node2:50051"},
		{"node3", "node3:50051"},
		{"node4", "node4:50051"},
		{"node5", "node5:50051"},
	}

	// Filter out current node
	for _, node := range allNodes {
		if node.id != s.nodeId {
			s.otherNodes = append(s.otherNodes, node)
		}
	}

	return s
}

func (s *RaftServer) AppendEntries(ctx context.Context, req *pb.AppendEntriesRequest) (*pb.AppendEntriesResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	sendReport(req.LeaderId, s.nodeId, "AppendEntries", "Received")

	s.state = follower
	s.lastHeartbeat = time.Now()
	s.logs = req.Logs
	s.leaderId = req.LeaderId

	try {
		// Execute all logs from current commitIndex to leader's commitIndex
		for i := s.commitIndex + 1; i <= req.CommitIndex; i++ {
			operation := s.logs[i].O
			switch operation.OperationType {
			case "READ":
				dataItem := operation.DataItem
				value, exists := s.database[dataItem]
				action := fmt.Sprintf("Read %s = %v", dataItem, value)
				if !exists {
					action = fmt.Sprintf("Read %s = Not Found", dataItem)
				}
				sendReport(s.nodeId, s.nodeId, "None", action)

			case "WRITE":
				dataItem := operation.DataItem
				dataValue := operation.Value
				s.database[dataItem] = dataValue
				action := fmt.Sprintf("Write %s = %s", dataItem, dataValue)
				sendReport(s.nodeId, s.nodeId, "None", action)
			}
			s.term = s.logs[i].T
		}
		s.commitIndex = req.CommitIndex
		return &pb.AppendEntriesResponse{Success: true}, nil
	} catch err {
		log.Printf("Failed to sync logs: %v", err)
		return &pb.AppendEntriesResponse{Success: false}, nil
	}
}

func (s *RaftServer) RequestVote(ctx context.Context, req *pb.RequestVoteRequest) (*pb.RequestVoteResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	sendReport(req.CandidateId, s.nodeId, "RequestVote", "Received")

	if s.state == leader || s.votedFor != "" {
		return &pb.RequestVoteResponse{VoteGranted: false}, nil
	}

	s.votedFor = req.CandidateId
	return &pb.RequestVoteResponse{VoteGranted: true}, nil
}

func (s *RaftServer) RequestOperation(ctx context.Context, req *pb.RequestOperationRequest) (*pb.RequestOperationResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	sendReport(s.nodeId, s.nodeId, "RequestOperation", "Received")

	// Validate operation
	if (req.OperationType != "READ" && req.OperationType != "WRITE") || 
	   (req.OperationType == "WRITE" && req.DataItem == "") {
		return &pb.RequestOperationResponse{Success: false}, nil
	}

	if s.state != leader {
		return &pb.RequestOperationResponse{
			Success:    false,
			LeaderAddr: fmt.Sprintf("%s:50051", s.leaderId),
		}, nil
	}

	// Create new log entry
	log := &pb.Log{
		O: req,
		T: s.term,
		K: int64(len(s.logs) + 1),
	}
	s.logs = append(s.logs, log)

	// Send AppendEntries to all followers
	successCount := 1 // Start with 1 for leader
	var wg sync.WaitGroup
	responses := make(chan bool, len(s.otherNodes))

	for _, node := range s.otherNodes {
		wg.Add(1)
		go func(nodeId, addr string) {
			defer wg.Done()
			success := s.appendEntriesToFollower(nodeId, addr)
			responses <- success
		}(node.id, node.addr)
	}

	// Wait for all responses
	go func() {
		wg.Wait()
		close(responses)
	}()

	for success := range responses {
		if success {
			successCount++
		}
	}

	// Check if majority achieved
	if successCount > s.numberOfNodes/2 {
		s.commitIndex++
		if req.OperationType == "READ" {
			value, exists := s.database[req.DataItem]
			if !exists {
				return &pb.RequestOperationResponse{Success: true}, nil
			}
			return &pb.RequestOperationResponse{Success: true, Value: value}, nil
		} else { // WRITE
			s.database[req.DataItem] = req.Value
			return &pb.RequestOperationResponse{Success: true}, nil
		}
	}

	return &pb.RequestOperationResponse{Success: false}, nil
}

func (s *RaftServer) FetchLogs(ctx context.Context, req *pb.FetchLogsRequest) (*pb.FetchLogsResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	sendReport("Reporter", s.nodeId, "FetchLogs", "Received")
	return &pb.FetchLogsResponse{Logs: s.logs}, nil
}

func (s *RaftServer) runFollower() {
	sendReport(s.nodeId, s.nodeId, "None", "Starting Follower State")
	s.votedFor = ""

	electionTimeout := time.Duration(rand.Int63n(int64(electionTimeoutMax-electionTimeoutMin))) + electionTimeoutMin
	timer := time.NewTimer(electionTimeout)
	defer timer.Stop()

	for s.state == follower && s.running {
		select {
		case <-timer.C:
			s.mu.Lock()
			if time.Since(s.lastHeartbeat) > electionTimeout {
				s.state = candidate
			}
			s.mu.Unlock()
			return
		}
	}
}

func (s *RaftServer) runCandidate() {
	sendReport(s.nodeId, s.nodeId, "None", "Starting Candidate State")

	for s.state == candidate && s.running {
		s.mu.Lock()
		s.term++
		if s.votedFor == "" {
			s.votedFor = s.nodeId
		}
		s.mu.Unlock()

		// Request votes from all other nodes
		votesReceived := 1 // Vote for self
		var wg sync.WaitGroup
		votes := make(chan bool, len(s.otherNodes))

		for _, node := range s.otherNodes {
			wg.Add(1)
			go func(nodeId, addr string) {
				defer wg.Done()
				success := s.sendRequestVote(nodeId, addr)
				votes <- success
			}(node.id, node.addr)
		}

		go func() {
			wg.Wait()
			close(votes)
		}()

		for vote := range votes {
			if vote {
				votesReceived++
			}
		}

		s.mu.Lock()
		if votesReceived > s.numberOfNodes/2 {
			action := fmt.Sprintf("Won Election with Votes: %d", votesReceived)
			sendReport(s.nodeId, s.nodeId, "None", action)
			s.state = leader
			s.leaderId = s.nodeId
		} else {
			action := fmt.Sprintf("Lost Election with Votes: %d", votesReceived)
			sendReport(s.nodeId, s.nodeId, "None", action)
			s.votedFor = ""
			time.Sleep(time.Duration(rand.Int63n(int64(electionTimeoutMax-electionTimeoutMin))) + electionTimeoutMin)
		}
		s.mu.Unlock()
	}
}

func (s *RaftServer) runLeader() {
	sendReport(s.nodeId, s.nodeId, "None", "Starting Leader State")
	ticker := time.NewTicker(heartbeatTimeout)
	defer ticker.Stop()

	for s.state == leader && s.running {
		select {
		case <-ticker.C:
			var wg sync.WaitGroup
			for _, node := range s.otherNodes {
				wg.Add(1)
				go func(nodeId, addr string) {
					defer wg.Done()
					s.appendEntriesToFollower(nodeId, addr)
				}(node.id, node.addr)
			}
			wg.Wait()
		}
	}
}

func (s *RaftServer) sendRequestVote(nodeId, addr string) bool {
	sendReport(s.nodeId, nodeId, "RequestVote", "Sent")

	conn, err := grpc.Dial(addr, grpc.WithInsecure())
	if err != nil {
		log.Printf("Failed to connect to %s: %v", nodeId, err)
		return false
	}
	defer conn.Close()

	client := pb.NewRaftClient(conn)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()

	resp, err := client.RequestVote(ctx, &pb.RequestVoteRequest{
		Term:        s.term,
		CandidateId: s.nodeId,
	})

	if err != nil {
		log.Printf("Failed to send RequestVote to %s: %v", nodeId, err)
		return false
	}

	return resp.VoteGranted
}

func (s *RaftServer) appendEntriesToFollower(nodeId, addr string) bool {
	sendReport(s.nodeId, nodeId, "AppendEntries", "Sent")

	conn, err := grpc.Dial(addr, grpc.WithInsecure())
	if err != nil {
		log.Printf("Failed to connect to %s: %v", nodeId, err)
		return false
	}
	defer conn.Close()

	client := pb.NewRaftClient(conn)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()

	resp, err := client.AppendEntries(ctx, &pb.AppendEntriesRequest{
		LeaderId:    s.nodeId,
		CommitIndex: s.commitIndex,
		Logs:        s.logs,
	})

	if err != nil {
		log.Printf("Failed to append entries to %s: %v", nodeId, err)
		return false
	}

	return resp.Success
}

func (s *RaftServer) Start() {
	for s.running {
		switch s.state {
		case follower:
			s.runFollower()
		case candidate:
			s.runCandidate()
		case leader:
			s.runLeader()
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func (s *RaftServer) Stop() {
	s.running = false
}

func main() {
	lis, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}

	server := grpc.NewServer()
	raftServer := NewRaftServer()
	pb.RegisterRaftServer(server, raftServer)

	log.Printf("Starting gRPC server on :%d", port)

	// Wait for reporter to start
	time.Sleep(5 * time.Second)

	// Start the Raft server in a goroutine
	go raftServer.Start()

	if err := server.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}