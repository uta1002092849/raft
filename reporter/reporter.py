import grpc
import raft_pb2
import raft_pb2_grpc
from concurrent import futures


class Reporter(raft_pb2_grpc.ReportServicer):
    def __init__(self):
        self.report = []

    def SendReport(self, request, context):
        """
        Handle incoming Report message
        """
        self.report.append(request)
        time = request.timeStamp
        message = request.reportMessage
        print(f"{time}: {message}")
        return raft_pb2.ReportResponse(success=True)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    raft_pb2_grpc.add_ReportServicer_to_server(Reporter(), server)
    server.add_insecure_port('[::]:50052')
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()