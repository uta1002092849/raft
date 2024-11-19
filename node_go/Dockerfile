FROM golang:1.23.3-bookworm

WORKDIR /app

COPY go.mod go.sum ./

RUN go mod download

COPY . .

RUN go build -o main ./node.go

CMD ["./main"]

