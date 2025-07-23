EDGE_LEN      = 1220;
PROFILE       = 20;
PANEL_L       = 1200;
PANEL_W       = 540;
PANEL_T       = 35;
PANEL_MASS    = 6.4;
CORD_DIA      = 2.4;
CORD_BREAK_N  = 2400;
WIND_MPH      = 100;
DC_ISO_SIZE   = [110,70,75];
BOX_SIZE      = [200,120,75];
BAT_BOX       = [330,180,230];
SHOW_WIRES    = true;
EXPLODE       = false;

EDGE_OUT = EDGE_LEN + PROFILE*2;
$fn=48;

module extrusion(len, axis="x")
{
    size = axis=="x" ? [len, PROFILE, PROFILE] :
           axis=="y" ? [PROFILE, len, PROFILE] :
                        [PROFILE, PROFILE, len];
    color("lightgray")
        cube(size);
}

module bracket()
{
    color("lightgray")
        cube([PROFILE, PROFILE, PROFILE]);
}

module panel()
{
    color("black")
        cube([PANEL_L, PANEL_W, PANEL_T]);
}

module kevlar_loop(face_id)
{
    loop_r = PROFILE/2 + CORD_DIA;
    offs = PANEL_L/4;
    for(i=[0,1])
    {
        translate([i==0? -PANEL_L/2+offs : PANEL_L/2-offs, 0, PANEL_T])
            rotate([0,90,0])
                rotate_extrude(angle=180)
                    translate([loop_r,0,0])
                        circle(d=CORD_DIA);
    }
}

module dc_isolator(pos)
{
    color("#d7d7d7")
        translate(pos)
            cube(DC_ISO_SIZE);
}

module mc4_fuse(pos)
{
    fuse_len = 70;
    fuse_d = 15;
    color("#d7d7d7")
        translate(pos)
            rotate([0,90,0])
                cylinder(h=fuse_len, d=fuse_d);
}

module abs_box(pos)
{
    hole_d = 12;
    color("#d7d7d7")
        translate(pos)
            difference() {
                cube(BOX_SIZE);
                for(y=[BOX_SIZE[1]/3,BOX_SIZE[1]*2/3])
                    translate([0,y,BOX_SIZE[2]/2])
                        rotate([0,90,0])
                            cylinder(h=BOX_SIZE[0],d=hole_d,center=true);
            }
}

module battery_box(pos)
{
    color("#d7d7d7")
        translate(pos)
            cube(BAT_BOX);
}

module draw_wires()
{
    if (!SHOW_WIRES) return;
    wire_d = 4;
    color("black")
    {
        start_x = -EDGE_OUT/2 + DC_ISO_SIZE[0];
        y = -EDGE_OUT/2-DC_ISO_SIZE[1]/2-wire_d/2;
        z = -EDGE_OUT/2 + 10;
        cube([100, wire_d, wire_d]);
        translate([DC_ISO_SIZE[0]+100+70,0,0])
            cube([100, wire_d, wire_d]);
        translate([DC_ISO_SIZE[0]+100+70+100+BOX_SIZE[0],0,0])
            cube([100, wire_d, wire_d]);
        translate([-start_x,-EDGE_OUT/2-PANEL_T,PROFILE])
            cube([start_x, wire_d, wire_d]);
    }
}

module place_panel(face)
{
    pv_exp = EXPLODE ? 15 : 0;
    if(face==0) // front
    {
        translate([-PANEL_L/2, -EDGE_OUT/2-PANEL_T-pv_exp, PROFILE])
            rotate([0,0,0]) panel();
        translate([0,-EDGE_OUT/2-pv_exp,EDGE_OUT-PROFILE])
            kevlar_loop(face);
    }
    else if(face==1) // right
    {
        translate([EDGE_OUT/2+pv_exp, -PANEL_L/2, PROFILE])
            rotate([0,0,90]) panel();
        translate([EDGE_OUT/2+pv_exp,0,EDGE_OUT-PROFILE])
            rotate([0,0,90]) kevlar_loop(face);
    }
    else if(face==2) // back
    {
        translate([-PANEL_L/2, EDGE_OUT/2+pv_exp, PROFILE])
            rotate([0,0,180]) panel();
        translate([0,EDGE_OUT/2+pv_exp,EDGE_OUT-PROFILE])
            rotate([0,0,180]) kevlar_loop(face);
    }
    else if(face==3) // left
    {
        translate([-EDGE_OUT/2-pv_exp, -PANEL_L/2, PROFILE])
            rotate([0,0,-90]) panel();
        translate([-EDGE_OUT/2-pv_exp,0,EDGE_OUT-PROFILE])
            rotate([0,0,-90]) kevlar_loop(face);
    }
}

module electrical()
{
    hw_exp = EXPLODE ? 10 : 0;
    start_x = -EDGE_OUT/2;
    y = -EDGE_OUT/2-DC_ISO_SIZE[1];
    z = -EDGE_OUT/2 + hw_exp;
    dc_isolator([start_x, y, z]);
    fuse_x = start_x + DC_ISO_SIZE[0] + 100;
    mc4_fuse([fuse_x, y+DC_ISO_SIZE[1]/2, z]);
    box_x = fuse_x + 70 + 100;
    abs_box([box_x, y, z]);
    bat_x = box_x + BOX_SIZE[0] + 100;
    battery_box([bat_x, y, z]);
}

module cube_frame()
{
    e = EDGE_OUT;
    o = EXPLODE ? 3 : 0;
    for(x=[0,e-PROFILE])
    for(y=[0,e-PROFILE])
    {
        signx = x==0? -1:1;
        signy = y==0? -1:1;
        translate([x+signx*o, y+signy*o, 0])
            extrusion(e,"z");
    }
    for(y=[0,e-PROFILE])
    for(z=[0,e-PROFILE])
    {
        signy = y==0? -1:1;
        signz = z==0? -1:1;
        translate([0+signy*0, y+signy*o, z+signz*o])
            extrusion(e,"x");
    }
    for(x=[0,e-PROFILE])
    for(z=[0,e-PROFILE])
    {
        signx = x==0? -1:1;
        signz = z==0? -1:1;
        translate([x+signx*o, 0+signx*0, z+signz*o])
            extrusion(e,"y");
    }

    // brackets
    b_exp = EXPLODE ? 8 : 0;
    for(x=[0,e-PROFILE])
    for(y=[0,e-PROFILE])
    for(z=[0,e-PROFILE])
    {
        signx = x==0? -1:1;
        signy = y==0? -1:1;
        signz = z==0? -1:1;
        translate([x+signx*b_exp, y+signy*b_exp, z+signz*b_exp])
            bracket();
    }
}

module assembly()
{
    q = 0.00256*pow(WIND_MPH,2);
    F_wind = q*PANEL_L*PANEL_W*0.0929;
    safety = CORD_BREAK_N/(F_wind/2);
    echo("q",q);
    echo("F_wind",F_wind);
    echo("safety",safety);
    translate([-EDGE_OUT/2,-EDGE_OUT/2,-EDGE_OUT/2])
    {
        cube_frame();
        for(face=[0:3]) place_panel(face);
        electrical();
        draw_wires();
    }
}

assembly();
