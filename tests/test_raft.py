from node.node import RaftServicer
from node.asyn_node import RaftServicer as AsynRaftServicer
import time, asyncio
import pytest

# @pytest.mark.asyncio
# async def test_no_leader():
#     # As there is only one node, there should be no leader
#     node = RaftServicer()
#     await node.start()
    
#     # wait for 3 seconds
#     print("Waiting for 3 seconds")
#     time.sleep(3)
#     print("Done waiting")
    
#     assert node.leaderId == None
    
#     # stop the node
#     node.stop()

@pytest.mark.asyncio
async def test_election():
    # As there is only one node and total number of nodes is 1, it should become leader
    node = AsynRaftServicer()
    node.NUMBER_OF_NODES = 1        # set total number of nodes to 1
    node.otherNodes = []            # set other nodes to empty list
    await node.start()
    
    print("Here")
    time.sleep(3)
    print(node.leaderId)
    