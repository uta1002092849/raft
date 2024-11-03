import grpc
import logging
import raft_pb2
import raft_pb2_grpc

def run():
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = raft_pb2_grpc.RaftStub(channel)
        # message = raft_pb2.RequestOperationRequest(operationType="WRITE", dataItem="x", value = int(1998))
        # response = response = stub.RequestOperation(message)
        # if response.success:
        #     print("Success")
        # else:
        #     print("Failure")

        message = raft_pb2.RequestOperationRequest(operationType="READ", dataItem="x", value = 0)
        response = response = stub.RequestOperation(message)
        if response.success:
            print(response.value)
        else:
            print("Failure")

if __name__ == '__main__':
    logging.basicConfig()
    run()




