"""Evaluate the actual CPU ONNX path on reviewed validation/test images."""
from pathlib import Path
import argparse
import json
import os
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def overlap(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=lambda box:(box[2]-box[0])*(box[3]-box[1])
    return intersection/max(1e-9,area(a)+area(b)-intersection)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--model",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--threshold",type=float,default=.55)
    args=parser.parse_args()
    import cv2
    import numpy as np
    from autohsr.du_detector import _detect
    from autohsr.models import Scene
    data=json.loads(args.manifest.read_text(encoding="utf-8"))
    counts={split:dict(tp=0,fp=0,fn=0,images=0) for split in ("val","test")}
    results=[]
    args.output.mkdir(parents=True,exist_ok=True)
    for row in data["samples"]:
        if row["split"]=="train":
            continue
        image=cv2.imread(row["image"])
        start=time.perf_counter()
        predictions=_detect(Scene([],image),args.model.resolve(),args.threshold,tuple(data['names']))
        elapsed=(time.perf_counter()-start)*1000
        used=set()
        hits=[]
        summary=counts[row["split"]]
        summary["images"]+=1
        for prediction in predictions:
            candidates=[(overlap(prediction.box,b["xyxy"]),i) for i,b in enumerate(row["boxes"])
                        if data["names"][b["label"]]==prediction.text and i not in used]
            best=max(candidates,default=(0,None))
            matched=best[0]>=.5
            summary["tp" if matched else "fp"]+=1
            if matched:
                used.add(best[1])
            hits.append(dict(label=prediction.text,box=prediction.box,score=prediction.score,iou=best[0]))
            h,w=image.shape[:2]
            x1,y1,x2,y2=[round(v*(w if i%2==0 else h)) for i,v in enumerate(prediction.box)]
            cv2.rectangle(image,(x1,y1),(x2,y2),(0,255,0),2)
        summary["fn"]+=len(row["boxes"])-len(used)
        results.append(dict(id=row["id"],split=row["split"],ms=elapsed,predictions=hits))
        # The manifest images have already had account identifiers removed.
        if row["split"]=="test":
            cv2.imwrite(str(args.output/f"test-{row['id']}.jpg"),image)
    report=dict(counts=counts,threshold=args.threshold,
                median_ms=float(np.median([r["ms"] for r in results][1:])),frames=results)
    (args.output/"evaluation.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="frames"},indent=2))


if __name__=="__main__":
    main()
