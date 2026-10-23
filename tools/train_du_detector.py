"""Train the DU world detector from a locally reviewed, session-split manifest.

Training is optional tooling; PyTorch/Ultralytics are not runtime dependencies.
Raw screenshots, labels and checkpoints belong under ignored runs/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil


def prepare(manifest: Path, output: Path) -> Path:
    data=json.loads(manifest.read_text(encoding="utf-8"))
    names=data["names"]
    if names not in (["Target"],["Card"],["Enemy"],["Target","GateLocked","Enemy"]):
        raise ValueError("Expected Target-only gates, Card-only world cards, Enemy-only, or Target, GateLocked, Enemy")
    groups={}
    hashes={}
    counts=Counter()
    for item in data["samples"]:
        if item.get("reviewed") is not True:
            raise ValueError(f"Unreviewed image: {item['id']}")
        split=item["split"]
        if split not in ("train","val","test"):
            raise ValueError("Invalid split")
        group=item["session"]
        if group in groups and groups[group]!=split:
            raise ValueError(f"Session leakage: {group}")
        groups[group]=split
        source=Path(item["image"])
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest!=item["sha256"]:
            raise ValueError(f"Image changed after review: {source}")
        if digest in hashes and hashes[digest]!=split:
            raise ValueError("Duplicate image across splits")
        hashes[digest]=split
        image_dir=output/"images"/split
        label_dir=output/"labels"/split
        image_dir.mkdir(parents=True,exist_ok=True)
        label_dir.mkdir(parents=True,exist_ok=True)
        stem=f"{int(item['id']):04d}"
        shutil.copyfile(source,image_dir/(stem+source.suffix))
        labels=[]
        for box in item["boxes"]:
            cls=box["label"]
            x1,y1,x2,y2=box["xyxy"]
            if cls not in range(len(names)) or not (0<=x1<x2<=1 and 0<=y1<y2<=1):
                raise ValueError(f"Invalid box: {item['id']}")
            labels.append(f"{cls} {(x1+x2)/2:.7f} {(y1+y2)/2:.7f} {x2-x1:.7f} {y2-y1:.7f}")
            counts[(split,names[cls])]+=1
        (label_dir/(stem+".txt")).write_text("\n".join(labels),encoding="utf-8")
    output.mkdir(parents=True,exist_ok=True)
    config=output/"dataset.yaml"
    config.write_text(f"path: {json.dumps(str(output.resolve()))}\ntrain: images/train\nval: images/val\n"
                      +"names:\n"+"".join(f"  {i}: {name}\n" for i,name in enumerate(names)),encoding="utf-8")
    (output/"manifest.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Reviewed labels:",dict(counts),flush=True)
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=Path("runs/du-detector"))
    parser.add_argument("--weights",type=Path,help="Local YOLO11 checkpoint; required for training")
    parser.add_argument("--epochs",type=int,default=80)
    parser.add_argument("--imgsz",type=int,default=960)
    parser.add_argument("--prepare-only",action="store_true")
    args=parser.parse_args()
    config=prepare(args.manifest,args.output/"dataset")
    if args.prepare_only:
        return
    if args.weights is None or not args.weights.is_file():
        parser.error("Training requires --weights pointing to a local YOLO11 checkpoint")
    runtime_config=(args.output/'ultralytics').resolve()
    runtime_config.mkdir(parents=True,exist_ok=True)
    os.environ["YOLO_CONFIG_DIR"]=str(runtime_config)
    import torch
    from ultralytics import YOLO,settings
    settings.update({"sync":False})
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; verify the isolated training environment")
    model=YOLO(str(args.weights.resolve()))
    model.train(data=str(config.resolve()),epochs=args.epochs,imgsz=args.imgsz,batch=8,
                device=0,workers=0,seed=1717,deterministic=True,optimizer="AdamW",lr0=.001,
                patience=20,cache="ram",mosaic=.4,close_mosaic=10,mixup=0,fliplr=0,
                hsv_h=.01,hsv_s=.25,hsv_v=.25,degrees=3,translate=.15,scale=.35,
                project=str(args.output.resolve()),name="fit",exist_ok=False,plots=True)
    best=YOLO(model.trainer.best)
    metrics=best.val(data=str(config.resolve()),imgsz=args.imgsz,device=0,workers=0,
                     project=str(args.output.resolve()),name="held-out")
    exported=best.export(format="onnx",imgsz=args.imgsz,opset=17,simplify=False,
                         dynamic=False,half=False,nms=False,device="cpu")
    summary={"classes":best.names,"metrics":metrics.results_dict,"onnx":str(exported),
             "weights":str(model.trainer.best),"training_gpu":torch.cuda.get_device_name(0),
             "torch":torch.__version__,"validation":"separate reviewed capture sessions"}
    (args.output/"training-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__":
    main()
