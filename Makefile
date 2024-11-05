# VARIABLES
PROTO_FILE = "raft.proto"

# Target
.PHONY: generate_grpc_python

generate_grpc_python:
	python -m grpc_tools.protoc -I. --python_out=./node --grpc_python_out=./node $(PROTO_FILE)
	python -m grpc_tools.protoc -I. --python_out=./reporter --grpc_python_out=./reporter $(PROTO_FILE)