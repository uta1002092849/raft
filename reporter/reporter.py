import grpc
import raft_pb2
import raft_pb2_grpc
from concurrent import futures
from flask import Flask, render_template, jsonify, request
import threading
import queue
from typing import List, Dict
from collections import deque
from datetime import datetime
import logging

# Initialize the Flask app
app = Flask(__name__)

class SafeReporter(raft_pb2_grpc.ReportServicer):
    def __init__(self, max_reports: int = 1000):
        self.max_reports = max_reports
        self._reports = deque(maxlen=max_reports)  # Thread-safe for append and pop
        self.lock = threading.RLock()  # Reentrant lock for more complex operations
        self.report_queue = queue.Queue()  # Thread-safe queue for incoming reports
        self._start_background_worker()
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger('SafeReporter')

    def _start_background_worker(self):
        """Start a background thread to process reports from the queue"""
        def worker():
            while True:
                try:
                    report = self.report_queue.get()
                    if report is None:  # Poison pill for clean shutdown
                        break
                    with self.lock:
                        self._reports.append(report)
                    self.report_queue.task_done()
                except Exception as e:
                    self.logger.error(f"Error processing report: {e}")

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def SendReport(self, request, context):
        """
        Thread-safe handling of incoming Report messages
        """
        try:
            report = {
                "time": request.timeStamp,
                "sender": request.sender,
                "receiver": request.receiver,
                "rpcType": request.rpcType,
                "action": request.action,
                "timestamp": datetime.now().isoformat()  # Add server-side timestamp
            }
            
            # Add to queue instead of directly to reports
            self.report_queue.put(report)
            
            return raft_pb2.ReportResponse(success=True)
        except Exception as e:
            self.logger.error(f"Error in SendReport: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return raft_pb2.ReportResponse(success=False)

    def get_reports(self) -> List[Dict]:
        """
        Thread-safe retrieval of reports
        """
        with self.lock:
            return list(self._reports)  # Create a new list from the deque

    def cleanup(self):
        """Clean shutdown of the reporter"""
        self.report_queue.put(None)  # Send poison pill
        self.worker_thread.join(timeout=5.0)

class SafeGRPCServer:
    def __init__(self, reporter: SafeReporter, port: int = 50052):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        self.reporter = reporter
        self.port = port
        raft_pb2_grpc.add_ReportServicer_to_server(reporter, self.server)
        
    def start(self):
        self.server.add_insecure_port(f'[::]:{self.port}')
        self.server.start()
        
    def stop(self):
        self.reporter.cleanup()
        self.server.stop(grace=5.0).wait()

# Initialize the SafeReporter
reporter = SafeReporter()
grpc_server = SafeGRPCServer(reporter)

def grpc_serve():
    """
    Start the gRPC server with proper error handling
    """
    try:
        grpc_server.start()
        grpc_server.server.wait_for_termination()
    except Exception as e:
        logging.error(f"gRPC server error: {e}")
    finally:
        grpc_server.stop()

# Flask routes with proper error handling
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/reports')
def get_reports():
    try:
        return jsonify(reporter.get_reports())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/operation', methods=['POST'])
def operation():
    leader_addr = 'node1:50051'
    try:
        # Leader connection retry logic with timeout
        for retry in range(3):
            try:
                with grpc.insecure_channel(leader_addr) as channel:
                    stub = raft_pb2_grpc.RaftStub(channel)
                    message = raft_pb2.RequestOperationRequest(
                        operationType="READ",
                        dataItem="x",
                        value=0
                    )
                    response = stub.RequestOperation(
                        message,
                        timeout=5.0  # 5 second timeout
                    )
                    if not response.success and response.leaderAddr:
                        leader_addr = response.leaderAddr
                    break
            except grpc.RpcError as e:
                if retry == 2:
                    raise e
                continue

        data = request.json
        with grpc.insecure_channel(leader_addr) as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            message = raft_pb2.RequestOperationRequest(
                operationType=data['operationType'],
                dataItem=data['dataItem'],
                value=int(data['value']) if data.get('value') else 0
            )
            response = stub.RequestOperation(message, timeout=5.0)
            
            if response.success:
                return jsonify({
                    "success": True,
                    "value": response.value if data['operationType'] == "READ" else None
                })
            return jsonify({"success": False, "error": "Operation failed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/fetchLogs', methods=['POST'])
def fetch_logs():
    try:
        data = request.json
        with grpc.insecure_channel(f"{data['nodeAddr']}:50051") as channel:
            stub = raft_pb2_grpc.RaftStub(channel)
            response = stub.fetchLogs(
                raft_pb2.fetchLogsRequest(),
                timeout=5.0
            )
            return_logs = [
                {
                    "operationType": log.o.operationType,
                    "dataItem": log.o.dataItem,
                    "value": log.o.value
                }
                for log in response.logs
            ]
            return jsonify({"success": True, "logs": return_logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run gRPC server in a separate thread
    grpc_thread = threading.Thread(target=grpc_serve, daemon=True)
    grpc_thread.start()
    
    try:
        # Run the Flask server
        app.run(debug=False, host="0.0.0.0", port=5000)
    finally:
        # Cleanup on shutdown
        grpc_server.stop()