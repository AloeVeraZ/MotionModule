"""Draw the locked MotionModule harness as an original, editable illustration."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import html

OUT = Path(__file__).parent
W, H = 3200, 2800
im = Image.new('RGB', (W, H), 'white')
d = ImageDraw.Draw(im)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="white"/>']
INK='#172b3a'; RED='#d52c32'; BLACK='#26313b'; ORANGE='#ed8315'
COLORS=['#8d44ad','#247bcc','#009e83','#d2a000',BLACK]
fontroot=Path('C:/Windows/Fonts')
def font(size,bold=False):
    return ImageFont.truetype(str(fontroot/('arialbd.ttf' if bold else 'arial.ttf')),size)
def rect(box,fill,stroke=None,r=0,width=2):
    d.rounded_rectangle(box,r,fill,stroke,width)
    x,y,x2,y2=box
    svg.append(f'<rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" rx="{r}" fill="{fill}" stroke="{stroke or fill}" stroke-width="{width}"/>')
def line(points,color,width=5,halo=False):
    if halo: line(points,'white',width+5)
    d.line(points,fill=color,width=width,joint='curve')
    svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
def circle(x,y,r,fill,stroke=None,width=2):
    d.ellipse((x-r,y-r,x+r,y+r),fill,stroke,width)
    svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke or fill}" stroke-width="{width}"/>')
def text(x,y,s,size=28,color=INK,bold=False,anchor='la'):
    d.text((x,y),s,font=font(size,bold),fill=color,anchor=anchor)
    a='middle' if anchor.startswith('m') else 'start'
    svg.append(f'<text x="{x}" y="{y+size*.84}" font-family="Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{a}">{html.escape(s)}</text>')
def screw(x,y,label=None,small=False):
    a,r,s=(12,8,4) if small else (24,15,8)
    rect((x-a,y-a,x+a,y+a),'#52ad75','#276441',3)
    circle(x,y,r,'#d5dfde','#596b69',2)
    line([(x-s,y+s),(x+s,y-s)],'#596b69',2)
    if label: text(x,y-57,label,23,anchor='ma',bold=True)
def hole(x,y):
    circle(x,y,10,'#e7bd50','#6d5521',2)
    circle(x,y,5,'#223128')
def chip(x,y,w,h):
    rect((x,y,x+w,y+h),'#24343d','#101e25',3)
    for i in range(7):
        xx=x+10+i*(w-20)/6
        line([(xx,y-8),(xx,y)],'#bdc8cc',4)
        line([(xx,y+h),(xx,y+h+8)],'#bdc8cc',4)

text(100,42,'MotionModule / complete wiring',58,bold=True)
text(100,116,'Physical Pi header pins • every control wire is drawn end to end',29,color='#58707e')

# Power: two independent buses, switched positive and direct battery return.
rect((100,240,380,405),'#34424b','#19262e',18)
rect((110,250,143,395),'#1d2a33',6)
text(165,268,'12 V NiMH',35,'white',True)
text(165,322,'Battery + fuse',24,'#e0e9ed')
line([(380,275),(425,275)],RED,11)
line([(380,370),(425,370)],BLACK,11)
rect((412,256,459,388),'#f1c535','#ac8512',5)
text(435,413,'XT30',24,anchor='ma',bold=True)
line([(459,275),(520,275)],RED,11)
rect((520,245,620,310),'#34424b','#10232a',9)
text(570,255,'I / O',31,'white',True,'ma')
text(570,332,'Main switch',24,anchor='ma')
line([(620,275),(2320,275),(2320,2450)],RED,10)
line([(459,370),(2380,370),(2380,2490)],BLACK,10)
text(1750,224,'SWITCHED +12 V',28,RED,True)
text(1750,325,'BATTERY NEGATIVE / 0 V',28,BLACK,True)
text(2510,274,'Red branches: positive',27,RED,True)
text(2510,316,'Black branches: return',27,BLACK,True)
text(2510,368,'Wago joins at branch points',24,color='#58707e')

# Integrated USB-C converter, not a separate USB adapter.
rect((230,520,670,660),'#35444e','#14232d',13)
text(450,546,'12 V → 5 V',36,'white',True,'ma')
text(450,602,'USB-C buck converter',26,'white',False,'ma')
line([(720,275),(720,555),(670,555)],RED,9)
line([(765,370),(765,623),(670,623)],BLACK,9)
circle(720,275,9,RED); circle(765,370,9,BLACK)
text(700,520,'IN+',22,RED,bold=True)
text(700,635,'IN−',22,BLACK,bold=True)

# Servo converter and PCA9685.
rect((1170,435,1580,545),'#35444e','#14232d',11)
text(1375,449,'Servo buck converter',29,'white',True,'ma')
text(1375,493,'12 V → 5 V / 5 A',27,'white',False,'ma')
line([(1210,275),(1210,435)],RED,9)
line([(1540,370),(1540,435)],BLACK,9)
circle(1210,275,9,RED);circle(1540,370,9,BLACK)
rect((1080,620,1645,860),'#685299','#433461',12)
text(1345,637,'PCA9685 • 0x40',30,'white',True,'ma')
servo_labels=['VCC','SDA','SCL','OE','GND']
servo_pts={p:(1105,665+i*35) for i,p in enumerate([1,3,5,7,9])}
for i,label in enumerate(servo_labels):
    text(1128,652+i*35,label,22,'white',True)
chip(1280,695,105,70)
for i in range(16):
    x=1235+i*24
    for j in range(3):hole(x,794+j*20)
    text(x,769,str(i),13,'white',False,'ma')
text(1485,692,'V+ header',18,'white')
text(1485,716,'unused',18,'white')
hole(1470,710)
line([(1260,545),(1260,583),(1520,583),(1520,620)],ORANGE,8)
line([(1480,545),(1480,565),(1600,565),(1600,620)],BLACK,8)
screw(1520,620);screw(1600,620)
text(1520,653,'V+',22,'white',True,'ma');text(1600,653,'GND',22,'white',True,'ma')
text(1180,885,'16 servo outputs: PWM / V+ / GND',23)

# Pi 5, rotated like the installed controller: header right, USB below.
rect((190,930,865,2350),'#248457','#145e3d',28)
for x,y in [(228,970),(820,970),(228,2310),(820,2310)]:
    circle(x,y,25,'#c2ba82');circle(x,y,13,'white')
text(245,1000,'Raspberry Pi 5',42,'white',True)
text(245,1060,'40-pin GPIO header →',26,'#e0f2e9')
chip(300,1350,240,240)
text(420,1445,'BCM2712',24,'#d6e3ea',True,'ma')
chip(310,1750,165,135)
for y in [1150,1230,1640,1930]:
    for i in range(4):
        rect((280+i*67,y,310+i*67,y+33),'#bcbca6','#526e60',3)
rect((250,2210,345,2355),'#d1d9dc','#788991',8)
rect((405,2200,550,2365),'#d1d9dc','#788991',5)
rect((580,2200,715,2365),'#d1d9dc','#788991',5)
for x in [421,470,595,644]:rect((x,2290,x+30,2345),'#2874a5','#4f5e68',2)
text(297,2385,'USB-C power',25,anchor='ma',bold=True)
text(560,2385,'USB / Ethernet',25,anchor='ma')
# One captive cable from converter to actual Pi USB-C inlet.
line([(230,590),(120,590),(120,2440),(297,2440),(297,2350)],'#778894',23)
line([(230,590),(120,590),(120,2440),(297,2440),(297,2350)],'#edf0f2',15)
rect((272,2326,322,2388),'#d4dce0','#5d6e77',8)
text(110,760,'USB-C cable',25,bold=True)
text(110,800,'from the converter',23)

P={p:(750 if p%2 else 810,1140+((p-1)//2)*55) for p in range(1,41)}
rect((724,1103,839,2224),'#173c2b','#0b2d1f',5)
text(750,1074,'odd',19,'white',False,'ma');text(810,1074,'even',19,'white',False,'ma')

# Drivers stacked for readable tracing; names and pin assignments stay locked.
drivers=[(4,930,[15,13,18,16,14],['7 • spare','8 • spare']),
         (3,1380,[23,21,26,24,25],['5 • spare','6 • spare']),
         (1,1830,[37,35,33,31,39],['1 • front_left','2 • rear_left']),
         (2,2280,[40,38,36,32,34],['3 • front_right','4 • rear_right'])]
destinations=[]
for n,y,pins,motors in drivers:
    rect((1720,y,2260,y+345),'#267b98','#165468',15)
    text(1940,y+20,f'DRIVER {n}',35,'white',True,'ma')
    text(1940,y+64,'Dual H-bridge',24,'#e2f2f7',False,'ma')
    chip(1920,y+146,140,90)
    for i,p in enumerate(pins):
        xx,yy=1765,y+118+i*43
        label=['IN1','IN2','IN3','IN4','GND'][i]
        text(1790,yy-12,label,23,'white',True)
        text(1660,yy-32,f'P{p}',20,COLORS[i],True)
        destinations.append((p,(xx,yy),COLORS[i],n,i))
    # Heavy power returns go to battery bus, not control-header ground.
    line([(2320,y+88),(2190,y+88)],RED,9,True)
    line([(2380,y+158),(2190,y+158)],BLACK,9,True)
    circle(2320,y+88,9,RED);circle(2380,y+158,9,BLACK)
    screw(2190,y+88);screw(2190,y+158)
    text(2090,y+74,'VIN+',22,'white',True)
    text(2090,y+144,'VIN−',22,'white',True)
    for j,label in enumerate(motors):
        my=y+232+j*79
        text(2095,my-12,'A' if j==0 else 'B',24,'white',True)
        # A two-terminal pair goes only to its own motor.
        for k in range(2):
            yy=my-13+k*27
            line([(2160,yy),(2530+j*50,yy),(2610,yy),(2745,yy)],'#677683' if k else '#aa6849',6,True)
            screw(2160,yy,small=True)
        rect((2745,my-30,2890,my+30),'#ced6db','#718491',11)
        rect((2890,my-13,2930,my+13),'#7e929f','#536b79',3)
        text(2950,my-14,label,22,bold=True)

# Actual point-to-point control wiring, with white crossover clearance.
# Routing is deterministic: the endpoint map is the locked physical pin map.
for p,target,color,n,i in destinations:
    sx,sy=P[p]
    lane=1170+{4:0,3:135,1:270,2:405}[n]+i*17
    escape=sy+15 if p%2 else sy
    line([(sx,sy),(sx+18,escape),(lane,escape),(lane,target[1]),target],color,5,True)
    hole(*target)
    circle(*target,4,color)

# Servo logic originates at the five exact Pi header pins.
for i,(p,target) in enumerate(servo_pts.items()):
    sx,sy=P[p];lane=925+i*24
    color=['#be456b','#258bcc','#b7a01a','#7b4bb3',BLACK][i]
    line([(sx,sy),(sx+18,sy+15),(lane,sy+15),(lane,target[1]),target],color,5,True)
    hole(*target);circle(*target,4,color)

# All forty physical header positions are visible; unused ones stay empty.
used={p for p,*_ in destinations}|set(servo_pts)
for p,(x,y) in P.items():
    hole(x,y)
    if p in used:circle(x,y,5,'#eef5f0')
    text(x,y-30,str(p),19,'white',True,'ma')

text(1030,2595,'Thin wires = control signals + signal ground',25,color='#4d6371')
text(1030,2640,'Heavy red / black wires = battery power',25,color='#4d6371')
line([(100,2710),(3095,2710)],'#cdd8df',2)
text(100,2740,'Physical pin numbers, not BCM GPIO. Crossings connect only at dots. Board drawings are schematic; follow terminal labels.',24)
svg.append('</svg>')
im.save(OUT/'motionmodule-complete-wiring.png')
(OUT/'motionmodule-complete-wiring.svg').write_text('\n'.join(svg),encoding='utf-8')
print(OUT/'motionmodule-complete-wiring.png')
