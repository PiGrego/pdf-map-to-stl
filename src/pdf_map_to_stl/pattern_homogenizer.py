from __future__ import annotations
import cv2
import numpy as np


def _remove_linear_components(mask: np.ndarray, min_elongation=8.0, max_thickness_px=18, min_length_px=80):
    """Remove long thin straight artefacts while retaining compact symbols."""
    n,lab,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    out=np.zeros_like(mask,dtype=np.uint8);removed=[]
    for i in range(1,n):
        x,y,w,h,area=stats[i];long=max(w,h);short=max(1,min(w,h));elong=long/short
        component=(lab==i).astype(np.uint8)
        # Oriented rectangle avoids rejecting a diagonal compact feature solely by bbox.
        pts=np.column_stack(np.where(component>0))[:,::-1].astype(np.float32)
        rw,rh=(0,0)
        if len(pts)>=3:(_, _),(rw,rh),_=cv2.minAreaRect(pts)
        o_long=max(rw,rh);o_short=max(1.0,min(rw,rh));o_elong=o_long/o_short
        reject=(long>=min_length_px and min(short,o_short)<=max_thickness_px and max(elong,o_elong)>=min_elongation)
        if reject:removed.append({'area_px':int(area),'bbox':[int(x),int(y),int(w),int(h)],'elongation':float(max(elong,o_elong))})
        else:out[lab==i]=1
    return out,removed


def _fill_clustered_small_holes(yellow: np.ndarray):
    """Fill only repeated small holes inside yellow, not ordinary courtyards."""
    inv=(1-yellow).astype(np.uint8)
    n,lab,stats,cent=cv2.connectedComponentsWithStats(inv,8)
    h,w=yellow.shape;candidate=np.zeros_like(yellow,dtype=np.uint8)
    # Small white dots at 600 dpi are typically tens to a few hundred pixels.
    centers=[];ids=[]
    for i in range(1,n):
        x,y,bw,bh,area=stats[i]
        if x==0 or y==0 or x+bw>=w or y+bh>=h:continue
        if 18<=area<=900 and max(bw,bh)/max(1,min(bw,bh))<=2.2:
            centers.append(cent[i]);ids.append(i)
    if not centers:return yellow.copy(),0
    centers=np.array(centers)
    filled=yellow.copy();count=0
    # Require at least 3 nearby holes, a robust signature of the white-dot pattern.
    for idx,i in enumerate(ids):
        d=np.linalg.norm(centers-centers[idx],axis=1)
        if np.count_nonzero(d<=70)>=3:
            filled[lab==i]=1;count+=1
    return filled,count


def _solidify_yellow_dot_fields(yellow: np.ndarray):
    """Convert white fields containing regular yellow dots to a homogeneous area."""
    n,lab,stats,_=cv2.connectedComponentsWithStats(yellow.astype(np.uint8),8)
    dots=np.zeros_like(yellow,dtype=np.uint8);dot_count=0
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        elong=max(w,h)/max(1,min(w,h));fill=area/max(1,w*h)
        # Repeated yellow stipple elements are small, compact components.
        if 12<=area<=700 and elong<=2.2 and fill>=0.22:
            dots[lab==i]=1;dot_count+=1
    if dot_count<3:return yellow.copy(),0
    # Connect neighbours only inside dense dot fields. 41 px at 600 dpi ~= 4.9 pt.
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(41,41))
    support=cv2.dilate(dots,kernel,iterations=1)
    support=cv2.morphologyEx(support,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(31,31)))
    ns,ls,ss,_=cv2.connectedComponentsWithStats(support,8)
    accepted=np.zeros_like(yellow,dtype=np.uint8);regions=0
    for i in range(1,ns):
        x,y,w,h,area=ss[i]
        if area<900:continue
        # At least five original dot components must participate.
        local=dots[y:y+h,x:x+w]
        nd=cv2.connectedComponents(local,8)[0]-1
        if nd>=5:
            accepted[ls==i]=1;regions+=1
    # Erode back to approximate the envelope through dot centres, then fill it.
    accepted=cv2.erode(accepted,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(23,23)),iterations=1)
    return np.maximum(yellow,accepted),regions


def homogenize_patterns(yellow: np.ndarray):
    stage1,white_holes=_fill_clustered_small_holes(yellow)
    stage2,yellow_dot_regions=_solidify_yellow_dot_fields(stage1)
    return stage2,{'white_dots_filled':int(white_holes),'yellow_dot_regions_solidified':int(yellow_dot_regions)}

# Public alias used by Final Candidate reports.
remove_linear_components = _remove_linear_components
