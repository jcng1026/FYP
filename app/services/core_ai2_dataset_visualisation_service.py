"""Non-destructive labelled-page evidence rendering."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app.models.core_ai2_dataset_types import REGION_COLOURS

def render_overlay(page, destination, invalid_region_ids=()):
    source=Path(page["source_image_path"]); destination=Path(destination)
    invalid=set(invalid_region_ids)
    with Image.open(source) as original:
        image=original.convert("RGB").copy()
    draw=ImageDraw.Draw(image); w,h=image.size; font=ImageFont.load_default()
    draw.rectangle((0,0,w,22),fill="#111827")
    draw.text((6,5),f"Profile {page['profile_id']} | {page['page_id']}",fill="white",font=font)
    for region in page.get("regions",[]):
        x,y,rw,rh=region["normalized_bbox"]; box=(round(x*w),round(y*h),round((x+rw)*w),round((y+rh)*h))
        colour="#FF00FF" if region.get("region_id") in invalid else REGION_COLOURS.get(region.get("region_type"),"#FF00FF")
        draw.rectangle(box,outline=colour,width=4 if region.get("region_id") in invalid else 2)
        text=f"{region.get('region_type','?')} | {region.get('region_label','?')}"
        tx,ty=box[0],max(23,box[1]-12); bounds=draw.textbbox((tx,ty),text,font=font)
        draw.rectangle(bounds,fill=colour); draw.text((tx,ty),text,fill="white",font=font)
    destination.parent.mkdir(parents=True,exist_ok=True); image.save(destination,"PNG")
    return destination
