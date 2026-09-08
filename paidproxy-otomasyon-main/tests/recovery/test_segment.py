from proxy_pipeline.queue.segments import Segment

def test_segment_checkpoint_recovery(tmp_path):
    path=tmp_path/"segment"; path.write_text("one\ntwo\n")
    first=Segment("s1","m1",path,cursor=1,state="PARTIAL"); first.checkpoint()
    second=Segment("s1","m1",path); second.recover()
    assert (second.cursor, second.state)==(1,"PARTIAL")
