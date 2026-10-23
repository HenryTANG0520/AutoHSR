"""Read visible damage-type colors from the target bar and attack icon."""

def _colors(image):
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    hue,saturation,value=hsv[:,:,0],hsv[:,:,1],hsv[:,:,2]
    vivid=(saturation>125)&(value>210)
    masks={
        "fire":vivid&((hue<12)|(hue>175)),
        "ice":vivid&(hue>=85)&(hue<105),
        "wind":vivid&(hue>=65)&(hue<85),
        "imaginary":vivid&(hue>=20)&(hue<40),
        "lightning":vivid&(hue>=135)&(hue<170),
        "quantum":vivid&(hue>=112)&(hue<135),
        "physical":(saturation<35)&(value>160)&(value<245),
    }
    return {name:int(np.count_nonzero(mask)) for name,mask in masks.items()}


def visible_elements(scene):
    if scene.image is None:
        return None,set()
    import cv2
    image=cv2.resize(scene.image,(960,round(scene.image.shape[0]*960/scene.image.shape[1])))
    h,w=image.shape[:2]
    current=_colors(image[round(.897*h):round(.936*h),round(.866*w):round(.885*w)])
    # Colored strokes in the glyph dominate its circular dark background.
    ranked=sorted(current,key=current.get,reverse=True)
    active=ranked[0] if ranked and current[ranked[0]]>=5 else None
    bar=_colors(image[round(.084*h):round(.118*h),round(.46*w):round(.59*w)])
    weaknesses={name for name,count in bar.items() if count>=8}
    return active,weaknesses
