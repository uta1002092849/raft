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
HEARTBEAT_TIMEOUT = 100 / 1000  # 100ms
ELECTION_TIMEOUT_MIN = 150 / 1000  # 150ms
ELECTION_TIMEOUT_MAX = 300 / 1000  # 300ms
NUMBER_OF_NODES = 5
HOSTNAME = socket.gethostname()

# Send report to the reporter
def sendReport(sender, receiver, rpcType, action):
    with grpc.insecure_channel('reporter:50052') as channel:
        stub = raft_pb2_grpc.ReportStub(channel)
        # Get the current time in milliseconds
        current_time_ms = str(datetime.datetime.now())

        # only keep hours, minutes, seconds and milliseconds
        current_time_ms = current_time_ms[-15:]
        
        # Send the report
        try:
            stub.SendReport(raft_pb2.ReportRequest(timeStamp = current_time_ms, rpcType = rpcType, sender = sender, receiver = receiver, action = action))
        except grpc.RpcError as e:
            print(f"Failed to send report to reporter: {e}")


class RaftServicer(raft_pb2_grpc.RaftServicer):
    def __init__(self):
        # To keep track of the current state of the node
        self.states = ["FOLLOWER", "CANDIDATE", "LEADER"]
        self.stateIndex = 0
        
        # To keep track of the current term of the node
        self.term = 0
        self.c = -1 # Index of the most recently comitted operation
        
        # Get the system's hostname
        self.nodeId = HOSTNAME
        
        # To keep track of the node that the current node has voted for
        self.votedFor = None
        
        # To keep track of the logs of the current node
        self.logs = []

        # To simulate the state machine
        self.database = {}
        
        # Other nodes in the cluster (name, address), name will be the hostname specified in the docker-compose file
        self.otherNodes = [("node1", "node1:50051"), ("node2", "node2:50051"), ("node3", "node3:50051"), ("node4", "node4:50051"), ("node5", "node5:50051")]
        self.otherNodes = [node for node in self.otherNodes if node[0] != self.nodeId]  # Remove the current node from the list of other nodes
        
        # To keep track of the last time any communication was received
        self.previous_recorded_time = time.time()
        
        # To keep track of election timeout
        self.election_timeout = random.uniform(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)

        # For task management
        self.current_task = None
        self.running = True

        # To keep track of the leader
        self.leaderId = None

    def AppendEntries(self, request, context):
        """
        RPC call instanciated by the leader to heartbeat/sync the logs of the followers
        
        Args:
            request: The request object containing the leader's Id, most recent committed log index, and the entire log entries
            context: The context object
        Returns:
            A response object containing a boolean value for whether the logs are successfully synced
        """
        sendReport(sender=request.leaderId, receiver=self.nodeId, rpcType="AppendEntries", action="Received")
        
        self.stateIndex = 0                             # Roll back to the follower state as the leader has sent a heartbeat
        self.previous_recorded_time = time.time()       # Update the last time a heartbeat was received
        self.logs = request.logs                        # Sync the logs with the leader
        self.leaderId = request.leaderId                # Update the leaderId

        try:
            # Execute all the logs from current c to the leader's c (up to is the key word)
            for i in range(self.c + 1, request.c + 1):
                operation = self.logs[i].o
                operationType = operation.operationType
                if operationType == "READ":
                    dataItem = operation.dataItem
                    action = "Read " + dataItem + " = " + (str(self.database[dataItem]) if dataItem in self.database else "Not Found")
                    sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="None", action=action)
                elif operationType == "WRITE":
                    dataItem = operation.dataItem
                    dataValue = operation.value
                    self.database[dataItem] = dataValue
                    action = "Write " + dataItem + " = " + str(dataValue)
                    sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="None", action=action)
                self.term = self.logs[i].t
            self.c = request.c
            return raft_pb2.AppendEntriesResponse(success=True)
        except Exception as e:
            print(f"Failed to sync logs: {e}")
            return raft_pb2.AppendEntriesResponse(success=False)

    def RequestVote(self, request, context):
        """
        RPC call instanciated by the candidate to request votes from the nodes in the cluster
        
        Args:
            request: The request object containing the candidate's term, and the candidate's Id
            context: The context object
        Returns:
            A response object containing a boolean value for whether the vote is granted
        """
        sendReport(sender=request.candidateId, receiver=self.nodeId, rpcType="RequestVote", action="Received")
        
        # Check if the current node is a leader or has already voted for a candidate
        if self.states[self.stateIndex] == "LEADER" or self.votedFor is not None:
            return raft_pb2.RequestVoteResponse(voteGranted=False)
        
        # Otherwise, grant the vote to the candidate
        self.votedFor = request.candidateId
        return raft_pb2.RequestVoteResponse(voteGranted=True)
    

    async def RequestOperation(self, request, context):
        """
        Asynchronous RPC call instantiated by the client to request an operation to be performed
        """
        sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="RequestOperation", action="Received")
        
        # Check if this is a valid operation
        operationType = request.operationType
        dataItem = request.dataItem
        
        # This might not necessary here as we can validate this in the client side
        if (operationType != "READ" and operationType != "WRITE") or (operationType == "WRITE" and dataItem is None):
            return raft_pb2.OperationResponse(success=False)
        
        # If the request is sent to the non leader node
        if self.states[self.stateIndex] != "LEADER":
            # Redirect the client to the leader
            return raft_pb2.RequestOperationResponse(success=False, leaderAddr=self.leaderId + ":50051")
        
        # Construct Log object
        log = raft_pb2.Log(o=request, t=self.term, k=len(self.logs) + 1)
        self.logs.append(log)

        # Create tasks for all followers
        tasks = [
            self.append_entries_to_follower(follower_id, follower_addr)
            for follower_id, follower_addr in self.otherNodes
        ]
        
        # Wait for all responses (with success count starting at 1 for leader)
        results = await asyncio.gather(*tasks, return_exceptions=False)
        success_count = 1 + sum(1 for result in results if result is True)

        # If majority of the nodes have successfully appended the log, commit the log
        if success_count > NUMBER_OF_NODES // 2:
            self.c += 1
            if operationType == "READ":
                return raft_pb2.RequestOperationResponse(
                    success=True,
                    value=self.database[dataItem] if dataItem in self.database else None
                )
            elif operationType == "WRITE":
                value = request.value
                self.database[dataItem] = value
                return raft_pb2.RequestOperationResponse(success=True)
        else:
            return raft_pb2.RequestOperationResponse(success=False)
    
    
    def fetchLogs(self, request, context):
        """
        RPC call instanciated by the reporter to fetch the logs of the current node
        """
        sendReport(sender="Reporter", receiver=self.nodeId, rpcType="FetchLogs", action="Received")
        return raft_pb2.fetchLogsResponse(logs=self.logs)
    
    async def start_follower(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the follower state
        """
        sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="None", action="Starting Follower State")
        self.votedFor = None
        while self.states[self.stateIndex] == "FOLLOWER" and self.running:
            if time.time() - self.previous_recorded_time > HEARTBEAT_TIMEOUT:
                self.stateIndex = 1
            await asyncio.sleep(HEARTBEAT_TIMEOUT)
    
    async def start_candidate(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the candidate state
        """
        sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="None", action="Starting Candidate State")
        while self.states[self.stateIndex] == "CANDIDATE" and self.running:
            
            self.term += 1
            
            # Send RequestVote RPCs to other nodes
            tasks = [
                self.send_request_vote(id, addr) for id, addr in self.otherNodes
            ]
            
            # Wait for all responses
            results = await asyncio.gather(*tasks)
            
            # count the votes
            success_count = (1 if self.votedFor == None else 0) + sum(1 for result in results if result is True)
            
            # Check if we've won the election
            if success_count > NUMBER_OF_NODES // 2:
                action = "Won Election with Votes: " + str(success_count)
                sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="None", action=action)
                self.stateIndex = 2 # Become leader
            # Otherwise, start a new election
            else:
                action = "Lost Election with Votes: " + str(success_count)
                sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="None", action=action)
                self.election_timeout = random.uniform(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)
                await asyncio.sleep(self.election_timeout)
                self.votedFor = None
    
    async def start_leader(self):
        """
            Asynchronous, non-blocking sub-routine if the node is in the leader state
        """
        sendReport(sender=self.nodeId, receiver=self.nodeId, rpcType="None", action="Starting Leader State")
        while self.states[self.stateIndex] == "LEADER" and self.running:
            tasks = [
                self.append_entries_to_follower(follower_id, follower_addr) for follower_id, follower_addr in self.otherNodes
            ]
            await asyncio.gather(*tasks)
            await asyncio.sleep(HEARTBEAT_TIMEOUT)
    
    async def send_request_vote(self, id, addr):
        """
        Asynchronous function to send a RequestVote RPC to another node
        """
        sendReport(sender=self.nodeId, receiver=id, rpcType="RequestVote", action="Sent")
        
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            try:
                response = await stub.RequestVote(
                    raft_pb2.RequestVoteRequest(term=int(self.term), candidateId=str(self.nodeId))
                )
                return response.voteGranted
            except grpc.RpcError as e:
                print(f"Failed to send RequestVote to {id}: {e}")
                return False

    async def append_entries_to_follower(self, follower_id, follower_addr):
        """
            Asynchronous function to send an AppendEntries RPC to another node
        """
        sendReport(sender=self.nodeId, receiver=follower_id, rpcType="AppendEntries", action="Sent")
        try:
            # Create async channel
            channel = grpc.aio.insecure_channel(follower_addr)
            stub = raft_pb2_grpc.RaftStub(channel)
            
            # Set timeout for RPC call
            async with channel:
                response = await stub.AppendEntries(
                    raft_pb2.AppendEntriesRequest(
                        leaderId=self.nodeId,
                        c=self.c,
                        logs=self.logs
                    ),
                )
                return response.success
        except Exception as e:
            print(f"Failed to append entries to {follower_id}: {e}")
    

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