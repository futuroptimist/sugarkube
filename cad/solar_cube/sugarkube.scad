$fn=48;

// Editable constants
EDGE_LEN      = 1220;      // inside cube edge, mm
PROFILE       = 20;        // extrusion width
PANEL_L       = 1200;      // PV length
PANEL_W       = 540;       // PV width
PANEL_T       = 35;        // PV frame depth
PANEL_MASS    = 6.4;       // kg per panel
CORD_DIA      = 2.4;       // Kevlar loop Ø
CORD_BREAK_N  = 2400;      // break strength, N
WIND_MPH      = 100;       // design gust
DC_ISO_SIZE   = [110,70,75];   // isolator housing (L×W×H)
BOX_SIZE      = [200,120,75];  // ABS enclosure
BAT_BOX       = [330,180,230]; // Group‑24 battery box footprint
SHOW_WIRES    = true;
EXPLODE       = false;

OUTER = EDGE_LEN + 2*PROFILE;
panel_gap = 10;

color_al = "lightgray";
color_glass = "black";
color_cord = "darkgray";
color_box = [0.82,0.84,0.84];

function explode_offset(signs,dist)=EXPLODE ? [signs[0]*dist,signs[1]*dist,signs[2]*dist]:[0,0,0];

module extrusion(len,axis){
  dims = axis==0 ? [len,PROFILE,PROFILE]
        : axis==1 ? [PROFILE,len,PROFILE]
        : [PROFILE,PROFILE,len];
  color(color_al) cube(dims);
}

module bracket(){
  color(color_al)
  union(){
    cube([PROFILE,PROFILE,PROFILE/3]);
    cube([PROFILE,PROFILE/3,PROFILE]);
    cube([PROFILE/3,PROFILE,PROFILE]);
  }
}

module panel(){
  color(color_glass) cube([PANEL_W,PANEL_T,PANEL_L]);
}

module kevlar_arc(r){
  rotate([0,90,0])
    rotate_extrude(angle=180)
      translate([r,0,0])
        circle(d=CORD_DIA);
}

module kevlar_loop(face_id){
  if(SHOW_WIRES){
    loop_r = PROFILE/2 + CORD_DIA;
    xoffs = [-PANEL_W/4,PANEL_W/4];
    top_z = -OUTER/2 + PROFILE + PANEL_L;
    if(face_id==0){
      for(xo=xoffs)
        translate([xo,OUTER/2+panel_gap,top_z]) kevlar_arc(loop_r);
    }else if(face_id==2){
      for(xo=xoffs)
        translate([xo,-OUTER/2-panel_gap,top_z]) rotate([0,180,0]) kevlar_arc(loop_r);
    }else if(face_id==1){
      for(yo=xoffs)
        translate([OUTER/2+panel_gap,yo,top_z]) rotate([0,0,90]) kevlar_arc(loop_r);
    }else if(face_id==3){
      for(yo=xoffs)
        translate([-OUTER/2-panel_gap,yo,top_z]) rotate([0,0,-90]) kevlar_arc(loop_r);
    }
  }
}

module dc_isolator(pos){
  color(color_box) translate(pos) cube(DC_ISO_SIZE,center=true);
}

module mc4_fuse(pos){
  color(color_box) translate(pos) cube([80,40,40],center=true);
}

module abs_box(pos){
  color(color_box)
  translate(pos)
  difference(){
    cube(BOX_SIZE,center=true);
    for(x=[-BOX_SIZE[0]/4,BOX_SIZE[0]/4])
      translate([x,BOX_SIZE[1]/2,0]) rotate([90,0,0]) cylinder(d=12,h=BOX_SIZE[1]+1);
  }
}

module battery_box(pos){
  color(color_box) translate(pos) cube(BAT_BOX,center=true);
}

module assembly(){
  translate([-OUTER/2,-OUTER/2,-OUTER/2]){
    // extrusions
    for(x=[0,OUTER-PROFILE])
    for(y=[0,OUTER-PROFILE]){
      off=explode_offset([x==0?-1:1,y==0?-1:1,0],3);
      translate([x+off[0],y+off[1],off[2]]) extrusion(OUTER,2);
    }
    for(y=[0,OUTER-PROFILE])
    for(z=[0,OUTER-PROFILE]){
      off=explode_offset([0,y==0?-1:1,z==0?-1:1],3);
      translate([off[0],y+off[1],z+off[2]]) extrusion(OUTER,0);
    }
    for(x=[0,OUTER-PROFILE])
    for(z=[0,OUTER-PROFILE]){
      off=explode_offset([x==0?-1:1,0,z==0?-1:1],3);
      translate([x+off[0],off[1],z+off[2]]) extrusion(OUTER,1);
    }

    // brackets
    for(x=[0,OUTER-PROFILE])
    for(y=[0,OUTER-PROFILE])
    for(z=[0,OUTER-PROFILE]){
      off=explode_offset([x==0?-1:1,y==0?-1:1,z==0?-1:1],8);
      translate([x+off[0],y+off[1],z+off[2]]) bracket();
    }

    bottom_z=-OUTER/2+PROFILE;
    // panels and loops
    for(face=[0:3]){
      if(face==0)
        translate([0,OUTER/2+panel_gap+PANEL_T/2,bottom_z+PANEL_L/2]) panel();
      else if(face==2)
        translate([0,-OUTER/2-panel_gap-PANEL_T/2,bottom_z+PANEL_L/2]) panel();
      else if(face==1)
        rotate([0,0,-90]) translate([0,OUTER/2+panel_gap+PANEL_T/2,bottom_z+PANEL_L/2]) panel();
      else if(face==3)
        rotate([0,0,90]) translate([0,OUTER/2+panel_gap+PANEL_T/2,bottom_z+PANEL_L/2]) panel();
      kevlar_loop(face);
    }

    // electrical hardware on front bottom rail
    base_x=-OUTER/2+DC_ISO_SIZE[0]/2+20;
    y_pos=OUTER/2+PROFILE/2;
    z_pos=bottom_z+DC_ISO_SIZE[2]/2;
    dc_isolator([base_x,y_pos,z_pos+10]);
    mc4_fuse([base_x+DC_ISO_SIZE[0]/2+40+40,y_pos,z_pos+10]);
    abs_box([base_x+DC_ISO_SIZE[0]/2+40+120+40,y_pos+0,z_pos+10]);
    battery_box([base_x+DC_ISO_SIZE[0]/2+40+120+40+BOX_SIZE[0]/2+100,y_pos,z_pos+10]);
  }
}

q=0.00256*pow(WIND_MPH,2);
F_wind=q*PANEL_L*PANEL_W*0.0929;
safety=CORD_BREAK_N/(F_wind/2);
echo("q=",q,"psf","F_wind=",F_wind,"N","safety=",safety);

assembly();
