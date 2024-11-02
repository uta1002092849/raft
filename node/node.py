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
def send_report(report):
    with grpc.insecure_channel('reporter:50052') as channel:
        stub = raft_pb2_grpc.ReportStub(channel)
        stub.SendReport(raft_pb2.ReportRequest(timeStamp = str(datetime.datetime.now()), reportMessage = report))


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
        # print(f'Process {self.nodeId} received RPC AppendEntries from Process {request.leaderId}.')
        report = f"Process {self.nodeId} received RPC AppendEntries from Process {request.leaderId}."
        send_report(report)
        
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
        report = f"Process {self.nodeId} received RPC RequestVote from Process {request.candidateId}."
        send_report(report)
        
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
        report = f"Process {self.nodeId} starting follower state"
        send_report(report)
        while self.states[self.stateIndex] == "FOLLOWER" and self.running:  # While the node is in the follower state
            self.follower_action()
            await asyncio.sleep(HEARTBEAT_TIMEOUT)
    
    async def start_candidate(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the candidate state
        """
        report = f"Process {self.nodeId} starting candidate state"
        send_report(report)
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
            report = ""
            if self.voteCount > NUMBER_OF_NODES // 2:
                report = f"Process {self.nodeId} won election with {self.voteCount} votes"
                self.stateIndex = 2 # Become leader
            # Otherwise, roll back to follower state
            else:
                report = f"Process {self.nodeId} lost election with {self.voteCount} votes"
                self.stateIndex = 0
                self.previous_recorded_time = time.time()
            send_report(report)
    
    async def start_leader(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the leader state
        """
        report = f"Process {self.nodeId} starting leader state"
        send_report(report)
        
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
        report = f'Process {self.nodeId} sending RPC RequestVote to Process {id}.'
        send_report(report)
        
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            try:
                response = await stub.RequestVote(
                    raft_pb2.RequestVoteRequest(term=int(self.term), candidateId=str(self.nodeId))
                )
                report = ""
                if response.voteGranted:
                    self.voteCount += 1
                    report = f"Process {self.nodeId} received vote from Process {id}."
                else:
                    report = f"Process {self.nodeId} did not receive vote from Process {id}."
                send_report(report)
            except grpc.RpcError as e:
                report = f"Process {self.nodeId} failed to send RPC RequestVote to Process {id}."
                send_report(report)


    async def send_append_entries(self, id, addr):
        """
            Asynchronous function to send an AppendEntries RPC to another node
        """
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            report = f"Process {self.nodeId} sending RPC AppendEntries to Process {id}."
            send_report(report)
            try:
                response = await stub.AppendEntries(
                    raft_pb2.AppendEntriesRequest(leaderId=str(self.nodeId), c=0, logs=self.logs)
                )
                report = ""
                if response.success:
                    report = f"Process {self.nodeId} successfully synced logs with Process {id}."
                else:
                    report = f"Process {self.nodeId} failed to sync logs with Process {id}."
                send_report(report)
            except grpc.RpcError as e:
                report = f"Process {self.nodeId} failed to send RPC AppendEntries to Process {id}."
                send_report(report)
    

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