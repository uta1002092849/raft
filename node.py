from concurrent import futures
import grpc
import time
import raft_pb2
import raft_pb2_grpc
import random

PORT = 50051
HEARTBEAT_TIMEOUT = 5
ELECTION_TIMEOUT_MIN = 10 
ELECTION_TIMEOUT_MAX = 15
NUMBER_OF_NODES = 5

class RaftServicer(raft_pb2_grpc.RaftServicer):
    def __init__(self, nodeId, otherNodes):
        self.states = ["FOLLOWER", "CANDIDATE", "LEADER"]
        self.stateIndex = 0
        self.term = 0
        self.nodeId = nodeId
        self.votedFor = None
        self.logs = []
        self.leaderId = None
        self.voteCount = 0
        self.otherNodes = otherNodes
        self.previous_heartbeat_time = time.time()
        self.election_timeout = random.randint(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)

    def AppendEntries(self, request, context):
        """
        RPC call instanciated by the leader to sync the logs of the followers
        
        Args:
            request: The request object containing the leader's Id, most recent committed log index, and the entire log entries
            context: The context object
        Returns:
            A response object containing a boolean value for whether the logs are successfully synced
        """
        
        # Get the current leader's term by checking the term of the last log entry
        current_leader_term = request.logs[-1].t
        if current_leader_term < self.term:
            return raft_pb2.AppendEntriesResponse(success=False)
        # Reset heartbeat timeout when heartbeat is received
        self.previous_heartbeat_time = time.time()
        
        # Sync the terms with the leader
        self.term = request.term
        
        # Set the leaderId to the current leader
        self.leaderId = request.leaderId
        
        # Sync the logs with the leader
        self.logs = request.logs
        
        # Remain in follower state if AppendEntries is received
        self.stateIndex = 0
        return raft_pb2.AppendEntriesResponse(success=True)

    def RequestVote(self, request, context):
        """
        RPC call instanciated by the candidate to request votes from the followers
        
        Args:
            request: The request object containing the candidate's term, and the candidate's Id
            context: The context object
        Returns:
            A response object containing a boolean value for whether the vote is granted
        """
        if request.term < self.term:
            return raft_pb2.RequestVoteResponse(voteGranted=False)
        # Once we
        if self.votedFor is None or self.votedFor == request.candidateId:
            self.votedFor = request.candidateId
            return raft_pb2.RequestVoteResponse(voteGranted=True)
        return raft_pb2.RequestVoteResponse(voteGranted=False)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    node = RaftServicer()
    raft_pb2_grpc.add_RaftServicer_to_server(node, server)
    server.add_insecure_port(f'[::]:{PORT}')
    server.start()
    print(f"gRPC server started on port {PORT}.")
    
    while True:
        current_time = time.time()

        # FOLLOWER State Logic
        if node.states[node.stateIndex] == "FOLLOWER":
            print("Follower state. Waiting for heartbeat.")
            if current_time - node.previous_heartbeat_time > node.election_timeout:
                node.stateIndex = 1  # Transition to candidate
                node.election_timeout = random.randint(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)
                print("Follower timed out. Transitioning to candidate.")

        # CANDIDATE State Logic
        elif node.states[node.stateIndex] == "CANDIDATE":
            # Check election timeout again
            if current_time - node.previous_heartbeat_time > node.election_timeout:
                node.previous_heartbeat_time = current_time
                node.term += 1
                node.voteCount = 1
                node.votedFor = node.nodeId
                node.election_timeout = random.randint(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)
                print("Start a new election. wait time: ", node.election_timeout)
                for peer in node.otherNodes:
                    # Send RequestVote RPC to each other node
                    print("Requesting votes from peers.")

            # Transition to LEADER if a majority is reached
            if node.voteCount > (NUMBER_OF_NODES // 2):
                node.stateIndex = 2  # Become leader
                node.previous_heartbeat_time = time.time()
                print("Elected as leader.")

        # LEADER State Logic
        elif node.states[node.stateIndex] == "LEADER":
            print("Leader state. Sending heartbeats.")
            if current_time - node.previous_heartbeat_time > HEARTBEAT_TIMEOUT:
                # Send AppendEntries RPC to all followers as heartbeat
                node.previous_heartbeat_time = current_time
                for peer in node.otherNodes:
                    # Assume `AppendEntries` sends heartbeats to other nodes
                    print("Sending heartbeat to followers.")
                time.sleep(HEARTBEAT_TIMEOUT)  # Ensure regular heartbeat interval

if __name__ == '__main__':
    serve()
