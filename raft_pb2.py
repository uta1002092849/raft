# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: raft.proto
# Protobuf Python Version: 5.27.2
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    5,
    27,
    2,
    '',
    'raft.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()



DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\nraft.proto\x12\x04raft\"&\n\x03Log\x12\t\n\x01o\x18\x01 \x01(\t\x12\t\n\x01t\x18\x02 \x01(\x05\x12\t\n\x01k\x18\x03 \x01(\x05\"L\n\x14\x41ppendEntriesRequest\x12\x10\n\x08leaderId\x18\x01 \x01(\t\x12\t\n\x01\x63\x18\x02 \x01(\x05\x12\x17\n\x04logs\x18\x03 \x03(\x0b\x32\t.raft.Log\"(\n\x15\x41ppendEntriesResponse\x12\x0f\n\x07success\x18\x01 \x01(\x08\"7\n\x12RequestVoteRequest\x12\x0c\n\x04term\x18\x01 \x01(\x05\x12\x13\n\x0b\x63\x61ndidateId\x18\x02 \x01(\t\"*\n\x13RequestVoteResponse\x12\x13\n\x0bvoteGranted\x18\x01 \x01(\x08\x32\x94\x01\n\x04Raft\x12H\n\rAppendEntries\x12\x1a.raft.AppendEntriesRequest\x1a\x1b.raft.AppendEntriesResponse\x12\x42\n\x0bRequestVote\x12\x18.raft.RequestVoteRequest\x1a\x19.raft.RequestVoteResponseB\x08Z\x06./raftb\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'raft_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  _globals['DESCRIPTOR']._loaded_options = None
  _globals['DESCRIPTOR']._serialized_options = b'Z\006./raft'
  _globals['_LOG']._serialized_start=20
  _globals['_LOG']._serialized_end=58
  _globals['_APPENDENTRIESREQUEST']._serialized_start=60
  _globals['_APPENDENTRIESREQUEST']._serialized_end=136
  _globals['_APPENDENTRIESRESPONSE']._serialized_start=138
  _globals['_APPENDENTRIESRESPONSE']._serialized_end=178
  _globals['_REQUESTVOTEREQUEST']._serialized_start=180
  _globals['_REQUESTVOTEREQUEST']._serialized_end=235
  _globals['_REQUESTVOTERESPONSE']._serialized_start=237
  _globals['_REQUESTVOTERESPONSE']._serialized_end=279
  _globals['_RAFT']._serialized_start=282
  _globals['_RAFT']._serialized_end=430
# @@protoc_insertion_point(module_scope)
