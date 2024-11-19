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

	pb "raft/raft"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const (
	PORT                 = 50051
	HEARTBEAT_TIMEOUT    = 10 * time.Second
	ELECTION_TIMEOUT_MIN = 15 * time.Second
	ELECTION_TIMEOUT_MAX = 30 * time.Second
)

type RaftNode struct {
	pb.UnimplementedRaftServer
	pb.UnimplementedReportServer

	// Node identification
	nodeID   string
	hostname string

	// State management
	states     []string
	stateIndex int
	mu         sync.RWMutex

	// Term and voting
	term      int32
	votedFor  string
	leaderId  string
	committed int32
	logs      []*pb.Log
	database  map[string]int32

	// Cluster configuration
	otherNodes []NodeInfo
	numNodes   int

	// Timeouts and timing
	previousRecordedTime time.Time
	electionTimeout      time.Duration

	// Cancellation and control
	ctx        context.Context
	cancelFunc context.CancelFunc
	running    bool
}

type NodeInfo struct {
	ID      string
	Address string
}

func NewRaftNode() *RaftNode {
	hostname, _ := os.Hostname()
	ctx, cancel := context.WithCancel(context.Background())

	node := &RaftNode{
		nodeID:     hostname,
		states:     []string{"FOLLOWER", "CANDIDATE", "LEADER"},
		stateIndex: 0,
		term:       0,
		votedFor:   "",
		logs:       []*pb.Log{},
		database:   make(map[string]int32),
		otherNodes: []NodeInfo{
			{ID: "node1", Address: "node1:50051"},
			{ID: "node2", Address: "node2:50051"},
			{ID: "node3", Address: "node3:50051"},
			{ID: "node4", Address: "node4:50051"},
			{ID: "node5", Address: "node5:50051"},
		},
		numNodes:             5,
		committed:            -1,
		ctx:                  ctx,
		cancelFunc:           cancel,
		running:              true,
		electionTimeout:      time.Duration(rand.Intn(int(ELECTION_TIMEOUT_MAX-ELECTION_TIMEOUT_MIN)) + int(ELECTION_TIMEOUT_MIN)),
		previousRecordedTime: time.Now(),
	}

	// Remove current node from other nodes
	filteredNodes := []NodeInfo{}
	for _, node := range node.otherNodes {
		if node.ID != hostname {
			filteredNodes = append(filteredNodes, node)
		}
	}
	node.otherNodes = filteredNodes

	return node
}

func (n *RaftNode) sendReport(sender string, receiver string, rpcType string, action string) (*pb.ReportResponse, error) {

	// open connection to reporter
	conn, err := grpc.NewClient("reporter:50052", grpc.WithTransportCredentials(insecure.NewCredentials()))

	if err != nil {
		log.Printf("Failed to connect to reporter: %v", err)
		return &pb.ReportResponse{Success: false}, nil
	}
	reporter := pb.NewReportClient(conn)

	currentTime := time.Now()
	currentTimeStr := currentTime.Format("15:04:05.000")

	// Construct report
	report := &pb.ReportRequest{
		TimeStamp: currentTimeStr,
		Sender:    sender,
		Receiver:  receiver,
		RpcType:   rpcType,
		Action:    action,
	}
	reportResponse, err := reporter.SendReport(context.Background(), report)

	if err != nil {
		log.Printf("Failed to send report: %v", err)
		return &pb.ReportResponse{Success: false}, nil
	}
	return reportResponse, nil
}

func (n *RaftNode) AppendEntries(ctx context.Context, req *pb.AppendEntriesRequest) (*pb.AppendEntriesResponse, error) {
	n.sendReport(req.LeaderId, n.nodeID, "AppendEntries", "Received")

	n.mu.Lock()
	defer n.mu.Unlock()

	n.stateIndex = 0 // Follower state
	n.previousRecordedTime = time.Now()
	n.logs = req.Logs
	n.leaderId = req.LeaderId

	// Execute logs from current committed index to leader's committed index
	for i := n.committed + 1; i <= req.C; i++ {
		operation := n.logs[i].O
		switch operation.OperationType {
		case "READ":
			n.sendReport(n.nodeID, n.nodeID, "None", fmt.Sprintf("Read %s", operation.DataItem))
		case "WRITE":
			n.database[operation.DataItem] = operation.Value
			n.sendReport(n.nodeID, n.nodeID, "None", fmt.Sprintf("Write %s = %d", operation.DataItem, operation.Value))
		}
		n.term = n.logs[i].T
	}
	n.committed = req.C
	return &pb.AppendEntriesResponse{Success: true}, nil
}

func (n *RaftNode) RequestVote(ctx context.Context, req *pb.RequestVoteRequest) (*pb.RequestVoteResponse, error) {
	n.sendReport(req.CandidateId, n.nodeID, "RequestVote", "Received")

	n.mu.Lock()
	defer n.mu.Unlock()

	if n.states[n.stateIndex] == "LEADER" || n.votedFor != "" {
		return &pb.RequestVoteResponse{VoteGranted: false}, nil
	}

	n.votedFor = req.CandidateId
	return &pb.RequestVoteResponse{VoteGranted: true}, nil
}

func (n *RaftNode) RequestOperation(ctx context.Context, req *pb.RequestOperationRequest) (*pb.RequestOperationResponse, error) {
	n.sendReport(n.nodeID, n.nodeID, "RequestOperation", "Received")

	n.mu.Lock()
	defer n.mu.Unlock()

	// Validate operation
	if req.OperationType != "READ" && req.OperationType != "WRITE" {
		return &pb.RequestOperationResponse{Success: false}, nil
	}

	if n.states[n.stateIndex] != "LEADER" {
		return &pb.RequestOperationResponse{
			Success:    false,
			LeaderAddr: fmt.Sprintf("%s:50051", n.leaderId),
		}, nil
	}

	// Create log entry
	log := &pb.Log{
		O: req,
		T: n.term,
		K: int32(len(n.logs) + 1),
	}
	n.logs = append(n.logs, log)

	// This is a simplified synchronous version for illustration
	successCount := 1
	for _, node := range n.otherNodes {
		if n.appendEntriesToFollower(node) {
			successCount++
		}
	}

	if successCount > n.numNodes/2 {
		n.committed++
		if req.OperationType == "READ" {
			value, exists := n.database[req.DataItem]
			if !exists {
				value = 0 // Default value if not found
			}
			return &pb.RequestOperationResponse{
				Success: true,
				Value:   value,
			}, nil
		}
		if req.OperationType == "WRITE" {
			n.database[req.DataItem] = req.Value
			return &pb.RequestOperationResponse{Success: true}, nil
		}
	}

	return &pb.RequestOperationResponse{Success: false}, nil
}

func (n *RaftNode) FetchLogs(ctx context.Context, req *pb.FetchLogsRequest) (*pb.FetchLogsResponse, error) {
	_ = ctx
	// consume fetch logs request to avoid error
	if req != nil {
		n.sendReport("Reporter", n.nodeID, "FetchLogs", "Received")

		n.mu.RLock()
		defer n.mu.RUnlock()

		n.sendReport("Reporter", n.nodeID, "FetchLogs", "Received")
		return &pb.FetchLogsResponse{
			Logs: n.logs,
		}, nil
	}
	return &pb.FetchLogsResponse{}, nil
}

func (n *RaftNode) appendEntriesToFollower(node NodeInfo) bool {

	n.sendReport(n.nodeID, node.ID, "AppendEntries", "Sent")
	conn, err := grpc.NewClient(node.Address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Printf("Failed to connect to %s: %v", node.Address, err)
		return false
	}
	defer conn.Close()

	client := pb.NewRaftClient(conn)
	resp, err := client.AppendEntries(context.Background(), &pb.AppendEntriesRequest{
		LeaderId: n.nodeID,
		C:        n.committed,
		Logs:     n.logs,
	})

	return err == nil && resp.Success
}

func (n *RaftNode) Start() {
	go func() {
		for n.running {
			switch n.states[n.stateIndex] {
			case "FOLLOWER":
				n.runFollower()
			case "CANDIDATE":
				n.runCandidate()
			case "LEADER":
				n.runLeader()
			}
		}
	}()
}

func (n *RaftNode) runFollower() {
	n.sendReport(n.nodeID, n.nodeID, "None", "Starting Follower State")

	n.mu.Lock()
	n.votedFor = ""
	n.mu.Unlock()

	for n.states[n.stateIndex] == "FOLLOWER" && n.running {
		if time.Since(n.previousRecordedTime) > n.electionTimeout {
			n.stateIndex = 1 // Move to candidate state
			return
		}
		time.Sleep(n.electionTimeout)
	}
}

func (n *RaftNode) runCandidate() {

	n.sendReport(n.nodeID, n.nodeID, "None", "Starting Candidate State")
	n.mu.Lock()

	n.term++
	if n.votedFor == "" {
		n.votedFor = n.nodeID
	}
	n.mu.Unlock()

	successCount := n.startElection()

	if successCount > n.numNodes/2 {
		n.sendReport(n.nodeID, n.nodeID, "None", fmt.Sprintf("Won election with Votes: %d", successCount))
		n.stateIndex = 2 // Become leader
		n.leaderId = n.nodeID
	} else {
		n.sendReport(n.nodeID, n.nodeID, "None", fmt.Sprintf("Lost election with Votes: %d", successCount))
		n.electionTimeout = time.Duration(rand.Intn(int(ELECTION_TIMEOUT_MAX-ELECTION_TIMEOUT_MIN)) + int(ELECTION_TIMEOUT_MIN))
		time.Sleep(n.electionTimeout)
	}
}

func (n *RaftNode) startElection() int {

	successCount := 0
	if n.votedFor == n.nodeID {
		successCount++
	}

	var mu sync.Mutex
	var wg sync.WaitGroup

	for _, node := range n.otherNodes {
		wg.Add(1)
		go func(node NodeInfo) {
			defer wg.Done()
			conn, err := grpc.NewClient(node.Address, grpc.WithTransportCredentials(insecure.NewCredentials()))
			if err != nil {
				return
			}
			defer conn.Close()

			client := pb.NewRaftClient(conn)
			resp, err := client.RequestVote(context.Background(), &pb.RequestVoteRequest{
				Term:        n.term,
				CandidateId: n.nodeID,
			})

			if err == nil && resp.VoteGranted {
				mu.Lock()
				successCount++
				mu.Unlock()
			}
		}(node)
	}

	wg.Wait()
	return successCount
}

func (n *RaftNode) runLeader() {
	n.sendReport(n.nodeID, n.nodeID, "None", "Starting Leader State")
	for n.states[n.stateIndex] == "LEADER" {
		for _, node := range n.otherNodes {
			n.appendEntriesToFollower(node)
		}
		time.Sleep(HEARTBEAT_TIMEOUT)
	}
}

func (n *RaftNode) Stop() {
	n.running = false
	n.cancelFunc()
}

func main() {
	raftNode := NewRaftNode()

	lis, err := net.Listen("tcp", fmt.Sprintf(":%d", PORT))
	if err != nil {
		log.Fatalf("failed to listen: %v", err)
	}

	grpcServer := grpc.NewServer()
	pb.RegisterRaftServer(grpcServer, raftNode)
	pb.RegisterReportServer(grpcServer, raftNode)

	go raftNode.Start()

	log.Printf("Starting gRPC server on port %d", PORT)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("failed to serve: %v", err)
	}
}
