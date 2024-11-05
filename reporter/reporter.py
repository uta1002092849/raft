import grpc
import raft_pb2
import raft_pb2_grpc
from concurrent import futures
from flask import Flask, render_template, jsonify, request
import sys
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

@app.route('/operation', methods=['POST'])
def operation():
    # Try to connect to the leader node
    leaderAddr = 'node1:50051'
    with grpc.insecure_channel(leaderAddr) as channel:
        stub = raft_pb2_grpc.RaftStub(channel)
        message = raft_pb2.RequestOperationRequest(
            operationType="READ",
            dataItem="x",
            value=0
        )
        response = stub.RequestOperation(message)
        if not response.success and response.leaderAddr is not None:
            leaderAddr = response.leaderAddr

    data = request.json
    try:
        with grpc.insecure_channel(leaderAddr) as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            message = raft_pb2.RequestOperationRequest(
                operationType=data['operationType'],
                dataItem=data['dataItem'],
                value=int(data['value']) if data['value'] else 0
            )
            response = stub.RequestOperation(message)
            
            if response.success:
                return jsonify({
                    "success": True,
                    "value": response.value if data['operationType'] == "READ" else None
                })
            return jsonify({"success": False, "error": "Operation failed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/fetchLogs', methods=['POST'])
def fetch_logs():
    data = request.json
    try:
        with grpc.insecure_channel(data['nodeAddr'] + ':50051') as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            message = raft_pb2.fetchLogsRequest()
            response = stub.fetchLogs(message)
            logs = response.logs
            returns_logs = []
            for log in logs:
                operation = log.o
                operationType = operation.operationType
                dataItem = operation.dataItem
                value = operation.value
                returns_logs.append({"operationType": operationType, "dataItem": dataItem, "value": value})
                
            return jsonify({"success": True, "logs": returns_logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == '__main__':
    # Run gRPC server in a separate thread
    grpc_thread = threading.Thread(target=grpc_serve)
    grpc_thread.start()
    
    # Run the Flask server
    app.run(debug=True, host="0.0.0.0", port=5000)
