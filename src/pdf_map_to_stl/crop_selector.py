from pathlib import Path
import json,cv2,fitz,numpy as np
from shapely.geometry import Polygon,box

def load_crop(path):return Polygon(json.loads(Path(path).read_text())['coordinates_pdf'])
def save_crop(path,pdf,page,poly):Path(path).write_text(json.dumps({'pdf':Path(pdf).name,'page':page,'coordinates_pdf':list(poly.exterior.coords),'bbox_pdf':list(poly.bounds)},indent=2))
def select_crop(page,full_page=False):
    if full_page:return box(0,0,page.rect.width,page.rect.height)
    z=2.;pix=page.get_pixmap(matrix=fitz.Matrix(z,z),alpha=False);im=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)[:,:,:3][:,:,::-1].copy();pts=[];title='V15 Final - crop: left add, right undo, Enter confirm, Esc cancel'
    def cb(e,x,y,f,p):
        if e==cv2.EVENT_LBUTTONDOWN:pts.append((x,y))
        elif e==cv2.EVENT_RBUTTONDOWN and pts:pts.pop()
    cv2.namedWindow(title,cv2.WINDOW_NORMAL);cv2.resizeWindow(title,min(1500,pix.width),min(920,pix.height));cv2.setMouseCallback(title,cb)
    try:
        while True:
            c=im.copy()
            if pts:cv2.polylines(c,[np.array(pts)],len(pts)>=3,(0,0,255),2)
            cv2.imshow(title,c);k=cv2.waitKey(20)&255
            if k in (10,13,32) and len(pts)>=3:break
            if k==27:raise RuntimeError('Crop cancelled')
    finally:cv2.destroyAllWindows()
    return Polygon([(x/z,y/z) for x,y in pts])
