# VARIABLES
PROTO_FILE = "raft.proto"

# Target
.PHONY: generate_grpc_python generate_grpc_go

generate_grpc_python:
	python -m grpc_tools.protoc -I. --python_out=./node_python --grpc_python_out=./node_python $(PROTO_FILE)
	python -m grpc_tools.protoc -I. --python_out=./reporter --grpc_python_out=./reporter $(PROTO_FILE)

generate_grpc_go:
	mkdir -p ./node_go
	protoc --go_out=./node_go --go-grpc_out=./node_go $(PROTO_FILE)
	echo "gRPC code for Go generated under ./node_go"
