from concurrent import futures
import grpc
import time
import raft_pb2
import raft_pb2_grpc
import random
import socket

PORT = 50051
HEARTBEAT_TIMEOUT = 5
ELECTION_TIMEOUT_MIN = 10
ELECTION_TIMEOUT_MAX = 15
NUMBER_OF_NODES = 5
HOSTNAME = socket.gethostname()


class RaftServicer(raft_pb2_grpc.RaftServicer):
    def __init__(self):
        
        # To keep track of the current state of the node
        self.states = ["FOLLOWER", "CANDIDATE", "LEADER"]
        self.stateIndex = 0
        
        # To keep track of the current term of the node
        self.term = 0
        
        # Get the system's hostname
        self.nodeId = HOSTNAME
        
        # To keep track of the node that the current node has voted for
        self.votedFor = None
        self.voteCount = 0  # To keep track of the votes received by node
        
        # To keep track of the logs of the current node
        self.logs = []
        
        # Other nodes in the cluster
        self.otherNodes = [("node1", "node1:50051"), ("node2", "node2:50051"), ("node3", "node3:50051"), ("node4", "node4:50051"), ("node5", "node5:50051")]
        # remove the current node from the list of other nodes
        self.otherNodes = [node for node in self.otherNodes if node[0] != self.nodeId]
        
        # To keep track of the last time a heartbeat was received
        self.previous_heartbeat_time = time.time()
        
        # Randomize the election timeout
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
        print(f'Process {self.nodeId} received RPC AppendEntries from Process {request.leaderId}.')
        
        # Roll back to the follower state
        self.stateIndex = 0
        
        # Reset follower's variables
        self.previous_heartbeat_time = time.time()
        self.votedFor = None
        self.voteCount = 0
        
        # Sync the logs with the leader
        self.logs = request.logs
        
        # For Q1, always return True
        return raft_pb2.AppendEntriesResponse(success=True)

    def RequestVote(self, request, context):
        """
        RPC call instanciated by the candidate to request votes from the nodes in the cluster
        
        Args:
            request: The request object containing the candidate's term, and the candidate's Id
            context: The context object
        Returns:
            A response object containing a boolean value for whether the vote is granted
        """
        print(f"Process {self.nodeId} received RPC RequestVote from Process {request.candidateId}.")
        
        # If the current node is in the LEADER state, it should not grant the vote
        if self.states[self.stateIndex] == "LEADER" or self.votedFor is not None:
            return raft_pb2.RequestVoteResponse(voteGranted=False)
        
        # Otherwise, grant the vote
        self.votedFor = request.candidateId
        return raft_pb2.RequestVoteResponse(voteGranted=True)

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
            if current_time - node.previous_heartbeat_time > HEARTBEAT_TIMEOUT:
                node.stateIndex = 1  # Transition to candidate
                node.election_timeout = random.randint(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)
                node.previous_heartbeat_time = time.time() # Set time to current time
                print("Heartbeat timeout. Transitioning to candidate state.")

        # CANDIDATE State Logic
        elif node.states[node.stateIndex] == "CANDIDATE":
            # Check election timeout again
            if current_time - node.previous_heartbeat_time > node.election_timeout:
                node.previous_heartbeat_time = current_time # set time to current time
                node.term += 1
                
                # Vote for self
                node.voteCount = 1
                node.votedFor = node.nodeId
                
                # Request votes from other nodes
                for id, addr in node.otherNodes:
                    with grpc.insecure_channel(addr) as channel:
                        stub = raft_pb2_grpc.RaftStub(channel)
                        print(f'Process {node.nodeId} sending RPC RequestVote to Process {id}.')
                        try:
                            response = stub.RequestVote(raft_pb2.RequestVoteRequest(term=int(node.term), candidateId=str(node.nodeId)))
                            if response.voteGranted:
                                node.voteCount += 1
                        except grpc.RpcError as e:
                            print(f"Error: {e.details()}")
                            continue

                # Transition to LEADER if a majority is reached
                if node.voteCount > (NUMBER_OF_NODES // 2):
                    node.stateIndex = 2
                    node.previous_heartbeat_time = time.time()
                    print(f"Process {node.nodeId} has become the leader.")
                # Transition back to FOLLOWER if not enough votes are received
                else:
                    node.stateIndex = 0
                    print(f"Process {node.nodeId} did not receive enough votes. Transitioning back to follower state.")
                    node.votedFor = None
                    node.voteCount = 0
                    node.previous_heartbeat_time = time.time()

        # LEADER State Logic
        elif node.states[node.stateIndex] == "LEADER":
            if current_time - node.previous_heartbeat_time > HEARTBEAT_TIMEOUT:
                # Send AppendEntries RPC to all followers as heartbeat
                node.previous_heartbeat_time = current_time
                for id, addr in node.otherNodes:
                    with grpc.insecure_channel(addr) as channel:
                        stub = raft_pb2_grpc.RaftStub(channel)
                        print(f"Process {node.nodeId} send RPC AppendEntries to Process {id}.")
                        # Hardcoded c value for Q1
                        try:
                            response = stub.AppendEntries(raft_pb2.AppendEntriesRequest(leaderId=str(node.nodeId), c=0, logs=node.logs))
                        except grpc.RpcError as e:
                            print(f"Error: {e.details()}")
                            continue
if __name__ == '__main__':
    serve()
