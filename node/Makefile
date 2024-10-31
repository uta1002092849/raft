# VARIABLES
PROTO_FILE = "raft.proto"

# Target
.PHONY: generate_grpc_python

generate_grpc_python:
	python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. $(PROTO_FILE)