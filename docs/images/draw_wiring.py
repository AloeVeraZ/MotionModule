"""Draw the locked MotionModule harness as an original, editable illustration."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import html
import re

OUT = Path(__file__).parent
W, H = 3800, 3500
SHIFT_X = 0
BG = '#111820'
im = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(im)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><rect width="100%" height="100%" fill="{BG}"/>']
INK='#e9f0f5'; RED='#ff525b'; BLACK='#0b1015'; ORANGE='#ffac42'
palette_path = Path(__file__).resolve().parents[2] / 'core/motion_module/static/wiring-palette.css'
PALETTE = dict(re.findall(r'--wire-([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;', palette_path.read_text(encoding='utf-8')))
DRIVER_COLORS = {
    n: [PALETTE[f'driver-{n}-{output}'] for output in ('a', 'a', 'b', 'b', 'ground')]
    for n in range(1, 5)
}
SERVO_COLORS = {1: PALETTE['servo-supply'], 3: PALETTE['servo-signal'],
                5: PALETTE['servo-signal'], 7: PALETTE['servo-signal'], 9: PALETTE['servo-ground']}
fontroot=Path('C:/Windows/Fonts')
def font(size,bold=False):
    return ImageFont.truetype(str(fontroot/('arialbd.ttf' if bold else 'arial.ttf')),size)
def rect(box,fill,stroke=None,r=0,width=2):
    box=(box[0]+SHIFT_X,box[1],box[2]+SHIFT_X,box[3])
    d.rounded_rectangle(box,r,fill,stroke,width)
    x,y,x2,y2=box
    svg.append(f'<rect x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" rx="{r}" fill="{fill}" stroke="{stroke or fill}" stroke-width="{width}"/>')
def line(points,color,width=5,halo=False):
    if halo: line(points,BG,width+7)
    if color == BLACK: line(points,'#8497a8',width+3)
    points=[(x+SHIFT_X,y) for x,y in points]
    d.line(points,fill=color,width=width,joint='curve')
    svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
def circle(x,y,r,fill,stroke=None,width=2):
    x+=SHIFT_X
    d.ellipse((x-r,y-r,x+r,y+r),fill,stroke,width)
    svg.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke or fill}" stroke-width="{width}"/>')
def text(x,y,s,size=28,color=INK,bold=False,anchor='la'):
    x+=SHIFT_X
    color={'#58707e':'#aabecd','#4d6371':'#aabecd',BLACK:'#b5c5d2'}.get(color,color)
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
line([(620,275),(2820,275),(2820,3210)],RED,10)
line([(459,370),(2880,370),(2880,3240)],BLACK,10)
text(1750,224,'SWITCHED +12 V',28,RED,True)
text(1750,325,'BATTERY NEGATIVE / 0 V',28,BLACK,True)
text(3010,274,'Red branches: positive',27,RED,True)
text(3010,316,'Black branches: return',27,BLACK,True)
text(3010,368,'Wago joins at branch points',24,color='#58707e')

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
SHIFT_X=400
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
servo_pts={p:(x+SHIFT_X,y) for p,(x,y) in servo_pts.items()}
SHIFT_X=0

# Pi 5: original top-down illustration informed by the official board photo.
# Portrait rotation: GPIO right, USB/Ethernet bottom; board aspect ~56:85.
# Reference: https://www.raspberrypi.com/products/raspberry-pi-5/
rect((190,960,1090,2326),'#217c4c','#40975d',30,4)
rect((205,975,1075,2311),'#217c4c','#72a36e',23,2)
for x,y in [(246,1016),(1034,1016),(246,1948),(1034,1948)]:
    circle(x,y,29,'#cbbb83','#d4ca9b',2);circle(x,y,16,BG)
# Subtle copper traces and surface-mount components keep the board recognisable.
for i in range(10):
    line([(420+i*15,1310),(420+i*15,1380+i*11),(740+i*15,1380+i*11),(740+i*15,1740)],'#348d58',2)
for i in range(8):
    line([(475,1800+i*14),(620+i*12,1800+i*14),(620+i*12,2150)],'#389060',2)
for bx,by,cols,rows in [(315,1190,6,3),(775,1530,5,5),(380,1810,4,4),(790,2100,5,3)]:
    for j in range(rows):
        for i in range(cols):
            x,y=bx+i*30,by+j*28
            rect((x,y,x+19,y+10),'#b8aa80','#d3c8a5',1)
            line([(x,y),(x,y+10)],'#ccd3c4',3)
            line([(x+19,y),(x+19,y+10)],'#ccd3c4',3)
text(620,986,'Raspberry Pi 5',28,'#e2efe1',True)
# Wi-Fi shield, memory, silver BCM2712 heat spreader, RP1 I/O controller.
rect((680,1080,895,1220),'#b8c5c2','#e4e9df',6,3)
text(787,1125,'WIRELESS',20,'#4b625c',False,'ma')
chip(515,1305,210,150)
text(620,1363,'LPDDR4X',22,'#cad8d1',True,'ma')
rect((480,1555,760,1835),'#435346','#13291e',8)
rect((496,1571,744,1819),'#c1c7ba','#eceee3',7,3)
text(620,1640,'BROADCOM',23,'#455548',True,'ma')
text(620,1685,'BCM2712',27,'#455548',True,'ma')
text(620,1730,'ARM',19,'#61705e',False,'ma')
chip(680,1925,220,160)
text(790,1970,'RP1',38,'#dce7de',True,'ma')
text(790,2023,'Raspberry Pi',17,'#b9cbc0',False,'ma')
# Raspberry-shaped silkscreen mark.
for dx,dy,r in [(0,0,17),(-20,17,19),(20,17,19),(-16,44,18),(16,44,18),(0,67,16)]:
    circle(365+dx,1435+dy,r,'#e6efe1')
line([(359,1430),(335,1411),(328,1400)],'#e6efe1',13)
line([(369,1430),(393,1411),(400,1400)],'#e6efe1',13)
# Power button and real left-edge USB-C input.
rect((177,1028,230,1080),'#b8c4c1','#e0e5dc',5)
circle(191,1054,13,'#394d42')
rect((166,1120,278,1222),'#c5cfcb','#6b8075',11,3)
rect((163,1138,192,1204),'#263b30','#ecf1e7',8)
text(288,1154,'USB-C',21,'#dce9dc',True)
# Both micro-HDMI sockets sit on the same left edge below USB-C.
for y,label in [(1460,'HDMI 0'),(1680,'HDMI 1')]:
    rect((174,y,260,y+105),'#b7c3bd','#e1e7dc',7)
    rect((172,y+19,200,y+86),'#33483d','#8d9e8e',4)
    text(274,y+34,label,20,'#dce9dc')
# Two camera/display FFCs and the separate PCIe connector.
for y,label in [(1870,'CAM / DISP 0'),(2075,'CAM / DISP 1')]:
    rect((211,y,287,y+157),'#e9e5d4','#afa98f',4)
    rect((211,y,229,y+157),'#504638','#82755c',2)
    for j in range(12):line([(236,y+10+j*12),(266,y+10+j*12)],'#cab477',3)
    text(308,y+59,label,18,'#dce9dc')
rect((438,978,595,1036),'#ebe6d4','#b5aa87',3)
rect((438,978,595,993),'#594c39',r=2)
text(456,1048,'PCIe',18,'#e1ece0')
for x,y,label in [(322,1300,'BAT'),(355,1640,'UART'),(998,2040,'FAN')]:
    rect((x,y,x+60,y+43),'#edece0','#b6beae',3)
    for i in range(3):rect((x+9+i*17,y+10,x+16+i*17,y+30),'#36483d',r=1)
    text(x,y+49,label,15,'#e1ece0')
# Bottom edge has Ethernet + two stacked USB sockets, not USB-C.
for x,w,label,insert in [(257,232,'ETHERNET','#202b27'),(557,207,'USB 3','#237cb6'),(823,207,'USB 2','#242d2b')]:
    rect((x,2150,x+w,2370),'#bcc7c5','#e0e5df',7,3)
    rect((x+12,2161,x+w-12,2320),'#aab8b4','#7c8e86',4)
    rect((x+12,2328,x+w-12,2363),'#263931',r=3)
    rect((x+24,2338,x+w-24,2357),insert,r=2)
    for off in [30,w-45]:rect((x+off,2180,x+off+15,2212),'#73887c',r=2)
    text(x+w/2,2390,label,22,anchor='ma',bold=True)
# Captive USB-C cable ends directly in the Pi's left-edge power port.
line([(230,590),(105,590),(105,1171),(166,1171)],'#778894',25)
line([(230,590),(105,590),(105,1171),(166,1171)],'#edf0f2',17)
rect((124,1148,187,1194),'#d4dce0','#5d6e77',8)
text(180,760,'USB-C power cable',25,bold=True)

P={p:(1000 if p%2 else 1045,1060+((p-1)//2)*42) for p in range(1,41)}
rect((975,1036,1070,1885),'#142a20','#080f0c',6,3)

# Drivers stacked for readable tracing; names and pin assignments stay locked.
drivers=[(4,950,[15,13,18,16,14],['7 • spare','8 • spare']),
         (3,1550,[23,21,26,24,25],['5 • spare','6 • spare']),
         (2,2150,[40,38,36,32,34],['3 • front_right','4 • rear_right']),
         (1,2750,[37,35,33,31,39],['1 • front_left','2 • rear_left'])]
destinations=[]
SHIFT_X=500
for n,y,pins,motors in drivers:
    rect((1720,y,2260,y+460),'#267b98','#165468',15)
    rect((1720,y,2260,y+8),DRIVER_COLORS[n][0],r=3)
    text(1940,y+20,f'DRIVER {n}',35,'white',True,'ma')
    text(1940,y+64,'Dual H-bridge',24,'#e2f2f7',False,'ma')
    chip(1920,y+146,140,90)
    for i,p in enumerate(pins):
        xx,yy=1765,y+145+i*60
        label=['IN1','IN2','IN3','IN4','GND'][i]
        text(1790,yy-12,label,23,'white',True)
        text(1660,yy-32,f'P{p}',20,INK if label == 'GND' else DRIVER_COLORS[n][i],True)
        destinations.append((p,(xx+SHIFT_X,yy),DRIVER_COLORS[n][i],n,i))
    # Heavy power returns go to battery bus, not control-header ground.
    line([(2320,y+88),(2190,y+88)],RED,9,True)
    line([(2380,y+158),(2190,y+158)],BLACK,9,True)
    circle(2320,y+88,9,RED);circle(2380,y+158,9,BLACK)
    screw(2190,y+88);screw(2190,y+158)
    text(2090,y+74,'VIN+',22,'white',True)
    text(2090,y+144,'VIN−',22,'white',True)
    for j,label in enumerate(motors):
        my=y+282+j*120
        text(2095,my-12,'A' if j==0 else 'B',24,'white',True)
        # A two-terminal pair goes only to its own motor.
        for k in range(2):
            yy=my-13+k*27
            line([(2160,yy),(2530+j*50,yy),(2610,yy),(2745,yy)],'#677683' if k else '#aa6849',6,True)
            screw(2160,yy,small=True)
        rect((2745,my-30,2890,my+30),'#ced6db','#718491',11)
        rect((2890,my-13,2930,my+13),'#7e929f','#536b79',3)
        text(2950,my-14,label,22,bold=True)

SHIFT_X=0
# Actual point-to-point control wiring, with background crossover clearance.
# Routing is deterministic: the endpoint map is the locked physical pin map.
for p,target,color,n,i in destinations:
    sx,sy=P[p]
    lane=1390+{1:0,2:200,3:400,4:600}[n]+i*28
    escape=sy+15 if p%2 else sy
    line([(sx,sy),(sx+18,escape),(lane,escape),(lane,target[1]),target],color,5,True)
    hole(*target)
    circle(*target,4,color)

# Servo logic originates at the five exact Pi header pins.
for i,(p,target) in enumerate(servo_pts.items()):
    sx,sy=P[p];lane=1230+i*24
    color=SERVO_COLORS[p]
    line([(sx,sy),(sx+18,sy+15),(lane,sy+15),(lane,target[1]),target],color,5,True)
    hole(*target);circle(*target,4,color)

# MPU6500 on the independent GPIO17/GPIO18 I2C bus.
# The owner's selected extension uses spare pins; motor/servo wiring is unchanged.
rect((360,2730,955,3240),'#284f84','#5180b7',16)
text(650,2750,'MPU6500 IMU • 0x68',33,'white',True,'ma')
chip(407,2880,110,115)
text(480,3060,'MPU6500',24,'white')
imu_pads=['VCC','GND','SCL','SDA','AD0','CS','AUX','INT']
imu_wires=[(17,0,PALETTE['imu-supply']),(6,1,PALETTE['imu-ground']),
           (12,2,PALETTE['imu-signal']),(11,3,PALETTE['imu-signal']),
           (20,4,PALETTE['imu-ground'])]
for i,label in enumerate(imu_pads):
    yy=2820+i*51
    text(740,yy-13,label,24,'white',True)
    hole(912,yy)
for i,(p,row,color) in enumerate(imu_wires):
    sx,sy=P[p]; lane=1120+i*21; ty=2820+row*51
    escape=sy+15 if p%2 else sy
    line([(sx,sy),(sx+18,escape),(lane,escape),(lane,ty),(912,ty)],color,5,True)
    hole(912,ty);circle(912,ty,4,color)
    label={17:'P17 · 3.3 V',12:'P12 · GPIO18',11:'P11 · GPIO17',6:'P6 · GND',20:'P20 · GND'}[p]
    text(540,ty-12,label,19,INK if p in (6,20) else color,bold=True)
text(1030,3090,'CS high for I2C: verify onboard pull-up',23,color='#aabecd')
text(1030,3130,'INT: disconnected • AD0 to P20 ground for 0x68',23,color='#aabecd')

# All forty physical header positions are visible; unused ones stay empty.
used={p for p,*_ in destinations}|set(servo_pts)|{p for p,_,_ in imu_wires}
pin_colors={p:color for p,_,color,_,_ in destinations}
pin_colors.update(SERVO_COLORS)
pin_colors.update({p:color for p,_,color in imu_wires})
for p,(x,y) in P.items():
    hole(x,y)
    if p in used:circle(x,y,5,pin_colors.get(p,'#eef5f0'))
    text(x,y-26,str(p),17,'white',True,'ma')

text(100,3320,'IMU setup in /boot/firmware/config.txt:  dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18',28)
text(100,3370,'Thin wires: control signals. Heavy red / black: battery power. Black wires have a light outline for visibility.',25,color='#aabecd')
line([(100,3420),(3695,3420)],'#4d6371',2)
text(100,3450,'Physical pin numbers, not BCM GPIO. Crossings connect only at dots. Board drawings are schematic; follow terminal labels.',24)
svg.append('</svg>')
im.save(OUT/'motionmodule-complete-wiring.png')
# Ship the same image with the dashboard for offline and installed use.
(palette_path.parent/'motionmodule-complete-wiring.png').write_bytes(
    (OUT/'motionmodule-complete-wiring.png').read_bytes())
(OUT/'motionmodule-complete-wiring.svg').write_text('\n'.join(svg),encoding='utf-8')
print(OUT/'motionmodule-complete-wiring.png')
