import grpc
import raft_pb2
import raft_pb2_grpc
from concurrent import futures
from flask import Flask, render_template, jsonify
import threading

# Initialize the Flask app
app = Flask(__name__)

class Reporter(raft_pb2_grpc.ReportServicer):
    def __init__(self):
        self.reports = []

    def SendReport(self, request, context):
        """
        Handle incoming Report message by adding it to the report list
        """
        time = request.timeStamp
        sender = request.sender
        receiver = request.receiver
        rpcType = request.rpcType
        action = request.action
        self.reports.append({"time": time, "sender": sender, "receiver": receiver, "rpcType": rpcType, "action": action})
        return raft_pb2.ReportResponse(success=True)

# Initialize the Reporter and shared reports list
reporter = Reporter()

def grpc_serve():
    """
    Start the gRPC server to handle incoming Report messages
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    raft_pb2_grpc.add_ReportServicer_to_server(reporter, server)
    server.add_insecure_port('[::]:50052')
    server.start()
    server.wait_for_termination()

@app.route('/')
def index():
    """
    Render the main page
    """
    return render_template('index.html')

@app.route('/reports')
def get_reports():
    """
    Endpoint to retrieve the list of reports in JSON format
    """
    return jsonify(reporter.reports)

if __name__ == '__main__':
    # Run gRPC server in a separate thread
    grpc_thread = threading.Thread(target=grpc_serve)
    grpc_thread.start()
    
    # Run the Flask server
    app.run(host="0.0.0.0", port=5000)
