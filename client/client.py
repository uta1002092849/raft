from flask import Flask, render_template, request, jsonify
import grpc
import raft_pb2
import raft_pb2_grpc

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

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

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5001)
