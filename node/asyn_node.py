from concurrent import futures
import grpc
import time
import raft_pb2
import raft_pb2_grpc
import random
import socket
import asyncio
import logging
import datetime

PORT = 50051
HEARTBEAT_TIMEOUT = 5
ELECTION_TIMEOUT_MIN = 10
ELECTION_TIMEOUT_MAX = 15
NUMBER_OF_NODES = 5
HOSTNAME = socket.gethostname()

# Send report to the reporter
def sendReport(sender, receiver, rpcType):
    with grpc.insecure_channel('localhost:50052') as channel:
        stub = raft_pb2_grpc.ReportStub(channel)
        # Get the current time in milliseconds
        current_time_ms = str(datetime.datetime.now())

        # only keep hours, minutes, seconds and milliseconds
        current_time_ms = current_time_ms[-15:]
        
        # Send the report
        try:
            stub.SendReport(raft_pb2.ReportRequest(timeStamp = current_time_ms, rpcType = rpcType, sender = sender, receiver = receiver))
        except grpc.RpcError as e:
            print(f"Failed to send report to reporter: {e}")


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
        
        # Other nodes in the cluster (name, address), name will be the hostname specified in the docker-compose file
        self.otherNodes = [("node1", "node1:50051"), ("node2", "node2:50051"), ("node3", "node3:50051"), ("node4", "node4:50051"), ("node5", "node5:50051")]
        self.otherNodes = [node for node in self.otherNodes if node[0] != self.nodeId]  # Remove the current node from the list of other nodes
        
        # To keep track of the last time any communication was received
        self.previous_recorded_time = time.time()
        
        # To keep track of election timeout
        self.election_timeout = None

        # Add task management
        self.current_task = None
        self.running = True

    def AppendEntries(self, request, context):
        """
        RPC call instanciated by the leader to heartbeat/sync the logs of the followers
        
        Args:
            request: The request object containing the leader's Id, most recent committed log index, and the entire log entries
            context: The context object
        Returns:
            A response object containing a boolean value for whether the logs are successfully synced
        """
        sendReport(sender=request.leaderId, receiver=self.nodeId, rpcType="AppendEntries")
        
        self.stateIndex = 0                             # Roll back to the follower state as the leader has sent a heartbeat
        self.previous_recorded_time = time.time()       # Update the last time a heartbeat was received
        self.votedFor = None                            # Reset the votedFor variable if current node was a candidate
        self.voteCount = 0                              # Reset the vote count  if current node was a candidate
        self.logs = request.logs                        # Sync the logs with the leader
        
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
        sendReport(sender=request.candidateId, receiver=self.nodeId, rpcType="RequestVote")
        
        # Check if the current node is a leader or has already voted for a candidate
        if self.states[self.stateIndex] == "LEADER" or self.votedFor is not None:
            return raft_pb2.RequestVoteResponse(voteGranted=False)
        
        # Otherwise, grant the vote to the candidate
        self.votedFor = request.candidateId
        return raft_pb2.RequestVoteResponse(voteGranted=True)
    
    async def start_follower(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the follower state
        """
        sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="Starting Follower State")
        while self.states[self.stateIndex] == "FOLLOWER" and self.running:  # While the node is in the follower state
            self.follower_action()
            await asyncio.sleep(HEARTBEAT_TIMEOUT)
    
    async def start_candidate(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the candidate state
        """
        sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="Starting Candidate State")
        while self.states[self.stateIndex] == "CANDIDATE" and self.running:
            self.election_timeout = random.randint(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)
            
            # Vote for self
            self.voteCount = 1
            self.term += 1
            self.votedFor = self.nodeId
            
            # Send RequestVote RPCs to other nodes
            self.candidate_action()
            
            # Wait for votes
            await asyncio.sleep(self.election_timeout)
            
            # Check if we've won the election
            if self.voteCount > NUMBER_OF_NODES // 2:
                sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="Won Election with Votes: " + str(self.voteCount))
                self.stateIndex = 2 # Become leader
            # Otherwise, roll back to follower state
            else:
                sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="Lost Election with Votes: " + str(self.voteCount))
                self.stateIndex = 0
                self.previous_recorded_time = time.time()
    
    async def start_leader(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the leader state
        """
        sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="Starting Leader State")
        
        while self.states[self.stateIndex] == "LEADER" and self.running:
            self.leader_action()
            await asyncio.sleep(HEARTBEAT_TIMEOUT)
    
    def follower_action(self):
        """
        Function to handle the actions of a follower node every heartbeat timeout
        """
        if time.time() - self.previous_recorded_time > HEARTBEAT_TIMEOUT:
            self.stateIndex = 1  # Transition to candidate
            self.previous_recorded_time = time.time()
    
    def candidate_action(self):
        """
            Send RequestVote RPCs to other nodes
        """
        for id, addr in self.otherNodes:
            asyncio.create_task(self.send_request_vote(id, addr))
    
    def leader_action(self):
        """
            Send AppendEntries RPCs to other nodes
        """
        for id, addr in self.otherNodes:
            asyncio.create_task(self.send_append_entries(id, addr))
    
    async def send_request_vote(self, id, addr):
        """
        Asynchronous function to send a RequestVote RPC to another node
        """
        sendReport(sender=self.nodeId, receiver=id, rpcType="RequestVote")
        
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            try:
                response = await stub.RequestVote(
                    raft_pb2.RequestVoteRequest(term=int(self.term), candidateId=str(self.nodeId))
                )
                if response.voteGranted:
                    self.voteCount += 1
            except grpc.RpcError as e:
                sendReport(sender=self.nodeId, receiver=id, rpcType="Failed to send RPC RequestVote")


    async def send_append_entries(self, id, addr):
        """
            Asynchronous function to send an AppendEntries RPC to another node
        """
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            sendReport(sender=self.nodeId, receiver=id, rpcType="AppendEntries")
            try:
                response = await stub.AppendEntries(
                    raft_pb2.AppendEntriesRequest(leaderId=str(self.nodeId), c=0, logs=self.logs)
                )
                # assume the logs are successfully synced for now
                # To Do
            except grpc.RpcError as e:
                sendReport(sender=self.nodeId, receiver=id, rpcType="Failed to send RPC AppendEntries")
    

    async def start(self):
        """Main loop to manage the node's state transitions"""
        while self.running:
            current_state = self.states[self.stateIndex]
            
            # Cancel the previous task if it exists
            if self.current_task:
                self.current_task.cancel()
                try:
                    await self.current_task
                except asyncio.CancelledError:
                    pass
            
            # Start the appropriate coroutine based on current state
            if current_state == "FOLLOWER":
                self.current_task = asyncio.create_task(self.start_follower())
            elif current_state == "CANDIDATE":
                self.current_task = asyncio.create_task(self.start_candidate())
            else:  # LEADER
                self.current_task = asyncio.create_task(self.start_leader())
            
            # Wait for the current task to complete
            try:
                await self.current_task
            except asyncio.CancelledError:
                pass
            
            await asyncio.sleep(0.1)  # Small delay to prevent busy waiting

    def stop(self):
        """Stop the node gracefully"""
        self.running = False
        if self.current_task:
            self.current_task.cancel()


async def serve():
    """Main function to start the gRPC server and the Raft node"""
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))
    node = RaftServicer()
    raft_pb2_grpc.add_RaftServicer_to_server(node, server)
    
    listen_addr = f'[::]:{PORT}'
    server.add_insecure_port(listen_addr)
    
    print(f"Starting gRPC server on {listen_addr}")
    await server.start()
    
    try:
        # Start the Raft node's main loop
        await node.start()
    
    except KeyboardInterrupt:
        print("Shutting down...")
        node.stop()
        await server.stop(5)

if __name__ == '__main__':
    logging.basicConfig()
    asyncio.run(serve())