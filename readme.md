# Raft Distributed Consensus Algorithm

This project implements a simplified version of the Raft consensus algorithm using gRPC and Flask. The system consists of multiple nodes that can communicate with each other to maintain a consistent state across the cluster. Additionally, a reporter service is used to log and display the operations performed by the nodes.

## Project Structure

- `node.py`: Implements the Raft node logic, including state transitions (Follower, Candidate, Leader), log replication, and handling client requests.
- `reporter.py`: Implements the reporter service that logs operations and provides a web interface to view the logs.
- `index.html`: The web interface for interacting with the Raft cluster and viewing logs.
- `raft.proto`: Protocol Buffers definition file for gRPC communication.

## Requirements

- Docker

## Installation & Running the project

1. Clone the repository:

   ```sh
   git clone https://github.com/mmt2849/raft.git
   cd raft
   ```

2. Run docker compose:

   ```sh
   docker compose up -d --build
   ```

3. Open the web interface in your browser:
   ```sh
   http://localhost:5000
   ```

## Usage

### Web Interface

- **Raft Client**: Use the form to perform `READ` and `WRITE` operations on the Raft cluster.
- **Fetch Logs**: Select a node and fetch its logs to view the operations performed.

### API Endpoints

- **GET `/reports`**: Retrieve the list of reports in JSON format.
- **POST `/operation`**: Perform an operation (`READ` or `WRITE`) on the Raft cluster.
- **POST `/fetchLogs`**: Fetch logs from a specific node.

## Acknowledgements

- [Raft Consensus Algorithm](https://raft.github.io/)
- [gRPC](https://grpc.io/)
- [Flask](https://flask.palletsprojects.com/)
