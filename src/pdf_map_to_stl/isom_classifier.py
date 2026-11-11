from dataclasses import dataclass
import math
@dataclass(frozen=True)
class Classification:tactile_layer:str;isom_symbol:str|None;confidence:float;semantic_class:str
PALETTE={
'yellow':[((255,186,54),'7_AREE_GIALLE','401'),((254,191,80),'7_AREE_GIALLE','401')],
'road_beige':[((246,218,195),'8_STRADE_BASE',None),((245,220,196),'8_STRADE_BASE',None)],
'green':[((61,255,23),'4_AIUOLE_E_SIEPI',None),((45,180,87),'4_AIUOLE_E_SIEPI',None),((159,186,0),'4_AIUOLE_E_SIEPI',None)],
'building':[((115,115,115),'2_EDIFICI',None),((138,140,142),'2_EDIFICI',None)],
'canopy':[((209,211,212),'3_PORTICI',None)],'water':[((0,157,221),'6_ACQUA_BLU',None)],
'black':[((0,0,0),'1_MURI_SPESSI',None),((35,31,32),'1_MURI_SPESSI',None)],
'white':[((255,255,255),'5_BOSCO_BIANCO','405')]}
class IsomClassifier:
 def __init__(self,max_distance=58):self.max_distance=max_distance
 def classify_rgb(self,rgb):
  if rgb is None:return Classification('NON_CLASSIFICATO',None,0,'none')
  best=min((math.dist(rgb,ref),name,layer,sym) for name,entries in PALETTE.items() for ref,layer,sym in entries)
  d,n,l,s=best
  return Classification(l,s,max(0,1-d/self.max_distance),n) if d<=self.max_distance else Classification('NON_CLASSIFICATO',None,0,'other')
