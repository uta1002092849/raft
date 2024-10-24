from concurrent import futures
import logging

import grpc
import time
import raft_pb2
import raft_pb2_grpc

PORT = 50051
HEARTBEAT_TIMEOUT = 100
ELECTION_TIMEOUT_MIN = 150
ELECTION_TIMEOUT_MAX = 300
NUMBER_OF_NODES = 5

class RaftServicer(raft_pb2_grpc.RaftServicer):
    def __init__(self):
        self.state = ["FOLLOWER", "CANDIDATE", "LEADER"]
        self.stateIndex = 0
        self.term = 0
        self.votedFor = None
        self.logs = []
        self.leaderId = None
        self.lastHeartbeat = time.time() * 1000
        self.voteReceived = set()
        self.otherNodes = []


    def AppendEntries(self, request, context):
        if request.term < self.term:
            return raft_pb2.AppendEntriesResponse(success=False)
        self.term = request.term
        self.leaderId = request.leaderId
        self.logs = request.logs
        return raft_pb2.AppendEntriesResponse(success=True)

    def RequestVote(self, request, context):
        if request.term < self.term:
            return raft_pb2.RequestVoteResponse(voteGranted=False)
        if self.votedFor is None or self.votedFor == request.candidateId:
            self.votedFor = request.candidateId
            return raft_pb2.RequestVoteResponse(voteGranted=True)
        return raft_pb2.RequestVoteResponse(voteGranted=False)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    raft_pb2_grpc.add_RaftServicer_to_server(RaftServicer(), server)
    server.add_insecure_port(f'[::]:{PORT}')
    server.start()
    try:
        while True:
            if RaftServicer.stateIndex == 0:
                # Follower
                pass
            elif RaftServicer.stateIndex == 1:
                # Candidate
                pass
            elif RaftServicer.stateIndex == 2:
                # Leader
                pass
    except KeyboardInterrupt as e:
        server.stop(0)

    server.wait_for_termination()

if __name__ == '__main__':
    logging.basicConfig()
    serve()