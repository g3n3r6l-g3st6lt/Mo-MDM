bl_info = {
    "name": "Mo's Maze Maker",
    "author": "Mo_G's brain + ChatGPT's brawn",
    "version": (2, 1, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar (N) > Mo's Maze Maker",
    "description": "A maze-generator that explores parsimony. The generator is highly adjustable to your preferences.",
    "category": "Add Mesh",
}

import bpy, random, math, os
from mathutils import Vector
from collections import deque
from heapq import heappush, heappop
from bpy.props import (
    IntProperty, FloatProperty, BoolProperty, FloatVectorProperty,
    PointerProperty, StringProperty, EnumProperty, CollectionProperty
)
from bpy.types import Operator, Panel, PropertyGroup, AddonPreferences

# ========= Runtime cache =========
LAST_MAZE_CACHE = None  # set by Generate

# ========= Presets (same logic as v1.3.1) =========
PRESET_DEFS = {
    'PURIST': {
        'label': "Purist (Minimalist)",
        'params': dict(step_cost=1.0, turn_penalty=0.0, alley_factor=0.0,
                       risk_penalty=0.0, expensive_penalty=0.0, certainty_bonus=0.0,
                       meander_turn_bias=1.3, meander_far_bias=0.9, meander_near_bias=0.2,
                       meander_avenue_pref=0.4),
        'algo': 'DIJKSTRA'
    },
    'CAUTIOUS': {
        'label': "Cautious",
        'params': dict(step_cost=1.0, turn_penalty=0.4, alley_factor=0.0,
                       risk_penalty=0.6, expensive_penalty=0.2, certainty_bonus=0.0,
                       meander_turn_bias=1.4, meander_far_bias=0.9, meander_near_bias=0.2,
                       meander_avenue_pref=0.4),
        'algo': 'DIJKSTRA'
    },
    'EXPERIENTIAL': {
        'label': "Experiential",
        'params': dict(step_cost=1.0, turn_penalty=0.15, alley_factor=0.15,
                       risk_penalty=0.2, expensive_penalty=0.1, certainty_bonus=0.05,
                       meander_turn_bias=1.6, meander_far_bias=1.1, meander_near_bias=0.25,
                       meander_avenue_pref=0.6),
        'algo': 'MEANDER'
    },
    'UTILITARIAN': {
        'label': "Utilitarian (Capacity)",
        'params': dict(step_cost=1.0, turn_penalty=0.2, alley_factor=0.6,
                       risk_penalty=0.0, expensive_penalty=0.1, certainty_bonus=0.0,
                       meander_turn_bias=1.3, meander_far_bias=0.8, meander_near_bias=0.2,
                       meander_avenue_pref=0.8),
        'algo': 'DIJKSTRA'
    },
    'FAITH': {
        'label': "Faith-guided",
        'params': dict(step_cost=1.0, turn_penalty=0.1, alley_factor=0.1,
                       risk_penalty=0.2, expensive_penalty=0.0, certainty_bonus=0.4,
                       meander_turn_bias=1.4, meander_far_bias=0.8, meander_near_bias=0.35,
                       meander_avenue_pref=0.3),
        'algo': 'DIJKSTRA'
    },
}
COST_PRESET_ITEMS = [
    ('PURIST', PRESET_DEFS['PURIST']['label'], ""),
    ('CAUTIOUS', PRESET_DEFS['CAUTIOUS']['label'], ""),
    ('EXPERIENTIAL', PRESET_DEFS['EXPERIENTIAL']['label'], ""),
    ('UTILITARIAN', PRESET_DEFS['UTILITARIAN']['label'], ""),
    ('FAITH', PRESET_DEFS['FAITH']['label'], ""),
]

# =========================
# Core utilities
# =========================
def sit_on_ground(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    o_eval = obj.evaluated_get(dg)
    corners_world = [o_eval.matrix_world @ Vector(c) for c in o_eval.bound_box]
    min_z = min(v.z for v in corners_world)
    obj.location.z -= min_z

def ensure_solid_material(name, rgba=(1,1,1,1)):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = rgba
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat

def get_collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        if parent is None:
            bpy.context.scene.collection.children.link(col)
        else:
            parent.children.link(col)
    return col

def get_maze_collection():    return get_collection("maze")
def get_paths_collection():   return get_collection("maze_paths")

def clear_collection_objects(col, name_prefixes=None):
    for ob in list(col.objects):
        if name_prefixes is None or any(ob.name.startswith(pref) for pref in name_prefixes):
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
            bpy.data.objects.remove(ob)

def link_exclusive(ob, target_col):
    if target_col not in ob.users_collection:
        target_col.objects.link(ob)
    for c in list(ob.users_collection):
        if c != target_col:
            c.objects.unlink(ob)

def select_only(objs):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        try: o.select_set(True)
        except: pass
    if objs:
        bpy.context.view_layer.objects.active = objs[0]

# =========================
# Maze generation
# =========================
def prims_maze(rows, cols, rng):
    H, W = rows*2+1, cols*2+1
    g = [[True for _ in range(W)] for _ in range(H)]
    sr, sc = rng.randrange(rows), rng.randrange(cols)
    cr, cc = sr*2+1, sc*2+1
    g[cr][cc] = False
    front = []
    def add_frontiers(r,c):
        for dr,dc in ((-2,0),(2,0),(0,-2),(0,2)):
            rr,cc = r+dr, c+dc
            if 1<=rr<H-1 and 1<=cc<W-1 and g[rr][cc]:
                front.append(((rr,cc),(r+dr//2,c+dc//2)))
    add_frontiers(cr,cc)
    while front:
        i = rng.randrange(len(front))
        (rr,cc),(br,bc) = front.pop(i)
        if g[rr][cc]:
            g[br][bc] = False
            g[rr][cc] = False
            add_frontiers(rr,cc)
    start = end = None
    for r in range(1, H-1):
        if not g[r][1]: g[r][0]=False; start=(r,0); break
    for r in range(H-2, 0, -1):
        if not g[r][W-2]: g[r][W-1]=False; end=(r,W-1); break
    return g, H, W, start, end

def inward(rc, rows, cols):
    r,c=rc
    if r==0: return (1,c)
    if r==rows-1: return (rows-2,c)
    if c==0: return (r,1)
    if c==cols-1: return (r,cols-2)
    return rc

def is_border_cell(r,c,rows,cols):
    return r==0 or c==0 or r==rows-1 or c==cols-1

def count_passages_and_deadends(grid):
    rows, cols = len(grid), len(grid[0])
    passages=0; dead=0
    for r in range(1,rows-1):
        for c in range(1,cols-1):
            if not grid[r][c]:
                passages+=1
                deg=0
                for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
                    rr,cc=r+dr,c+dc
                    if 0<=rr<rows and 0<=cc<cols and not grid[rr][cc]:
                        deg+=1
                if deg==1: dead+=1
    return passages, dead

def carve_loops_with_deadend_guard(grid, H, W, rng, ratio, min_deadend_ratio, min_deadend_abs):
    if ratio<=0: return
    cand=[]
    for r in range(1,H-1):
        for c in range(1,W-1):
            if grid[r][c]:
                if r%2==1 and c%2==0 and (not grid[r][c-1]) and (not grid[r][c+1]):
                    cand.append((r,c))
                if r%2==0 and c%2==1 and (not grid[r-1][c]) and (not grid[r+1][c]):
                    cand.append((r,c))
    rng.shuffle(cand)
    max_to=int(len(cand)*ratio)
    total,_ = count_passages_and_deadends(grid)
    min_dead = max(min_deadend_abs, math.ceil(total*min_deadend_ratio))
    carved=0
    for (r,c) in cand:
        if carved>=max_to: break
        grid[r][c]=False
        _, dead_after = count_passages_and_deadends(grid)
        if dead_after>=min_dead:
            carved+=1
        else:
            grid[r][c]=True

def merge_rectangles(grid, rows, cols):
    g=[row[:] for row in grid]
    blocks=[]
    for r in range(rows):
        c=0
        while c<cols:
            if not g[r][c]:
                c+=1; continue
            w=1
            while c+w<cols and g[r][c+w]: w+=1
            h=1
            while r+h<rows and all(g[r+h][cc] for cc in range(c,c+w)): h+=1
            for rr in range(r,r+h):
                for cc in range(c,c+w):
                    g[rr][cc]=False
            blocks.append((r,c,h,w))
            c+=w
    return blocks

# =========================
# Routing helpers (as in v1.3.1)
# =========================
def neighbors_passages(grid, r, c):
    rows, cols = len(grid), len(grid[0])
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr,cc=r+dr,c+dc
        if 0<=rr<rows and 0<=cc<cols and not grid[rr][cc]:
            yield rr,cc,dr,dc

def manhattan(a,b): return abs(a[0]-b[0])+abs(a[1]-b[1])

def compute_clearance_score(grid):
    rows, cols = len(grid), len(grid[0])
    score = [[0]*cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            if grid[r][c]: continue
            walls=0
            for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
                rr,cc=r+dr,c+dc
                if 0<=rr<rows and 0<=cc<cols and grid[rr][cc]:
                    walls+=1
            score[r][c]=walls  # 0 open, 4 narrow
    return score

def sample_zone_mask(grid, rng, density=0.0, border_margin=2):
    rows, cols=len(grid), len(grid[0])
    mask=[[False]*cols for _ in range(rows)]
    if density<=0: return mask
    for r in range(border_margin, rows-border_margin):
        for c in range(border_margin, cols-border_margin):
            if not grid[r][c] and rng.random()<density:
                mask[r][c]=True
    return mask

def reconstruct_path(prev, end_state):
    path=[]
    cur=end_state
    while cur in prev:
        (r,c,_), p = cur, prev[cur]
        path.append((r,c))
        cur=p
    (r,c,_)=cur
    path.append((r,c))
    return path[::-1]

def dijkstra_costed_path(grid, start, goal, params, clearance, risk_mask, expensive_mask, certainty_mask):
    rows, cols = len(grid), len(grid[0])
    def dir_index(dr,dc):
        if dr==0 and dc==0: return 0
        if dr==-1 and dc==0: return 1
        if dr==1 and dc==0: return 2
        if dr==0 and dc==-1: return 3
        if dr==0 and dc==1: return 4
        return 0

    step=params['step_cost']
    tau=params['turn_penalty']
    alley_factor=params['alley_factor']
    risk_p=params['risk_penalty']
    expensive_p=params['expensive_penalty']
    certainty_b=params['certainty_bonus']

    INF=10**12
    dist={}
    prev={}
    pq=[]
    s=(start[0], start[1], 0)
    dist[s]=0.0
    heappush(pq,(0.0, s))
    best_goal=None

    while pq:
        d, state = heappop(pq)
        if d!=dist.get(state, INF): continue
        r,c,pi = state
        if (r,c)==goal:
            best_goal=state; break
        for rr,cc,dr,dc in neighbors_passages(grid, r, c):
            ndir = dir_index(dr,dc)
            turn = tau if (pi!=0 and ndir!=pi) else 0.0
            walls_adj = clearance[rr][cc]
            alley = alley_factor * (walls_adj/4.0)
            risk = risk_p if risk_mask[rr][cc] else 0.0
            toll = expensive_p if expensive_mask[rr][cc] else 0.0
            certain = certainty_b if certainty_mask[rr][cc] else 0.0
            w = step + turn + alley + risk + toll - certain
            nd = d + max(0.0, w)
            ns=(rr,cc,ndir)
            if nd < dist.get(ns, INF):
                dist[ns]=nd
                prev[ns]=state
                heappush(pq,(nd, ns))

    if best_goal is None:
        return []
    return reconstruct_path(prev, best_goal)

def self_avoiding_meander(grid, start, goal, rng, params, clearance, risk_mask, expensive_mask, certainty_mask, trials=600):
    rows, cols = len(grid), len(grid[0])

    def reachable(start_node, blocked):
        if start_node in blocked or goal in blocked: return False
        Q=deque([start_node]); seen={start_node}
        while Q:
            v=Q.popleft()
            if v==goal: return True
            r,c=v
            for rr,cc,_,_ in neighbors_passages(grid, r, c):
                if (rr,cc) not in seen and (rr,cc) not in blocked:
                    seen.add((rr,cc)); Q.append((rr,cc))
        return False

    best=None
    turn_bias=params.get('meander_turn_bias',1.3)
    far_bias=params.get('meander_far_bias',0.9)
    near_bias=params.get('meander_near_bias',0.2)
    alley_pref=params.get('meander_avenue_pref',0.4)
    risk_pen=params['risk_penalty']
    expensive_pen=params['expensive_penalty']
    certain_bonus=params['certainty_bonus']

    for _ in range(trials):
        path=[start]
        visited={start}
        prev_dir=None
        ok=True
        while path[-1]!=goal:
            r,c=path[-1]
            cand=[]
            for rr,cc,dr,dc in neighbors_passages(grid, r, c):
                if (rr,cc) in visited: continue
                blocked=visited.copy(); blocked.add((rr,cc))
                if not reachable((rr,cc), blocked - {(rr,cc)}): continue
                turn = (1.0 if (prev_dir is not None and prev_dir!=(dr,dc)) else 0.0)
                dgoal = manhattan((rr,cc), goal)
                walls_adj = clearance[rr][cc]
                avenue_bonus = (1.0 - walls_adj/4.0)
                risk = 1.0 if risk_mask[rr][cc] else 0.0
                toll = 1.0 if expensive_mask[rr][cc] else 0.0
                certain = 1.0 if certainty_mask[rr][cc] else 0.0
                jitter = random.random()*0.05
                score = (-turn_bias*turn) + (-far_bias*dgoal) + (near_bias/(dgoal+1)) \
                        + (-alley_pref*avenue_bonus) + (risk_pen*risk*0.1) + (expensive_pen*toll*0.1) \
                        + (-certain_bonus*certain*0.1) + jitter
                cand.append(((rr,cc,dr,dc), score))
            if not cand: ok=False; break
            cand.sort(key=lambda x:x[1])
            topk=max(1,min(3,len(cand)))
            pick = random.choice(cand[:topk])[0]
            rr,cc,dr,dc=pick
            prev_dir=(dr,dc)
            path.append((rr,cc)); visited.add((rr,cc))
        if ok and path[-1]==goal:
            if best is None or len(path)>len(best):
                best=path
    if best is None:
        best = dijkstra_costed_path(grid, start, goal, {
            'step_cost':1.0,'turn_penalty':0.0,'alley_factor':0.0,
            'risk_penalty':0.0,'expensive_penalty':0.0,'certainty_bonus':0.0
        }, clearance, risk_mask, expensive_mask, certainty_mask)
    return best

# =========================
# Preferences: color presets (unchanged)
# =========================
class MMM_ColorPreset(bpy.types.PropertyGroup):
    name: StringProperty(name="Preset Name", default="Preset")
    col_default: FloatVectorProperty(size=4, subtype='COLOR', default=(1,1,1,1), min=0, max=1)
    col_purist:  FloatVectorProperty(size=4, subtype='COLOR', default=(0.55,0.30,0.95,1.0), min=0, max=1)
    col_explore: FloatVectorProperty(size=4, subtype='COLOR', default=(1.0,0.55,0.20,1.0), min=0, max=1)
    col_inter:   FloatVectorProperty(size=4, subtype='COLOR', default=(0.60,0.28,0.18,1.0), min=0, max=1)

class MMM_Preferences(AddonPreferences):
    bl_idname = __name__
    presets: CollectionProperty(type=MMM_ColorPreset)
    active_preset: IntProperty(name="Active Preset", default=-1)
    def draw(self, context):
        col = self.layout.column()
        col.label(text="Saved Color Presets")
        for i, pr in enumerate(self.presets):
            row = col.row(align=True)
            row.prop(pr, "name", text="")
            op = row.operator("mmm.delete_preset", text="", icon='TRASH')
            op.index = i

class MMM_OT_SavePreset(Operator):
    bl_idname = "mmm.save_preset"
    bl_label = "Save Color Preset"
    name: StringProperty(name="Preset Name", default="My Colors")
    def invoke(self, context, event): return context.window_manager.invoke_props_dialog(self)
    def execute(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        p = context.scene.mmm_props
        new = prefs.presets.add()
        new.name = self.name
        new.col_default = p.col_default
        new.col_purist  = p.col_route_a
        new.col_explore = p.col_route_b
        new.col_inter   = p.col_intersect
        prefs.active_preset = len(prefs.presets)-1
        self.report({'INFO'}, f"Saved preset '{self.name}'.")
        return {'FINISHED'}

class MMM_OT_ApplyPreset(Operator):
    bl_idname = "mmm.apply_preset"
    bl_label = "Apply Preset"
    preset_index: IntProperty(default=-1)
    def execute(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        if not prefs.presets:
            self.report({'WARNING'}, "No presets saved."); return {'CANCELLED'}
        idx = self.preset_index if self.preset_index >=0 else 0
        idx = max(0, min(idx, len(prefs.presets)-1))
        pr = prefs.presets[idx]
        p = context.scene.mmm_props
        p.col_default = pr.col_default
        p.col_route_a = pr.col_purist
        p.col_route_b = pr.col_explore
        p.col_intersect = pr.col_inter
        self.report({'INFO'}, f"Applied preset '{pr.name}'.")
        return {'FINISHED'}

class MMM_OT_DeletePreset(Operator):
    bl_idname = "mmm.delete_preset"
    bl_label = "Delete Preset"
    index: IntProperty()
    def execute(self, context):
        prefs = bpy.context.preferences.addons[__name__].preferences
        if 0<=self.index<len(prefs.presets):
            prefs.presets.remove(self.index)
            self.report({'INFO'}, "Preset deleted.")
            return {'FINISHED'}
        self.report({'WARNING'}, "Invalid preset index.")
        return {'CANCELLED'}

# =========================
# Scene Properties (NEW: per-start floor routes & start markers)
# =========================
class MMM_Props(PropertyGroup):
    # Size & seed
    rows: IntProperty(name="Rows", default=22, min=5, soft_max=300)
    cols: IntProperty(name="Cols", default=34, min=5, soft_max=300)
    randomize: BoolProperty(name="Use Random Seed", default=True)
    seed: IntProperty(name="Seed", default=12345, soft_min=0)

    # Geometry
    cell_w: FloatProperty(name="Cell W", default=2.5, min=0.01)
    cell_h: FloatProperty(name="Cell H", default=2.5, min=0.01)
    height_min: FloatProperty(name="Wall H min", default=7.0, min=0.01)
    height_max: FloatProperty(name="Wall H max", default=20.0, min=0.01)
    uniform_height: BoolProperty(name="Uniform Height", default=False)

    # Loops & dead-ends
    extra_loop_ratio: FloatProperty(name="Loop Ratio", default=0.06, min=0.0, max=1.0)
    keep_deadend_min_ratio: FloatProperty(name="Min Dead-End Ratio", default=0.06, min=0.0, max=1.0)
    keep_deadend_min_count: IntProperty(name="Min Dead-End Count", default=6, min=0)

    # Floor
    make_floor: BoolProperty(name="Make Floor", default=True)
    floor_thickness: FloatProperty(name="Floor Thickness", default=0.2, min=0.0)

    # Old wall-color set (still used for wall meshes if you want)
    col_default: FloatVectorProperty(name="Walls: Default", subtype='COLOR', size=4, default=(1,1,1,1), min=0, max=1)
    col_route_a: FloatVectorProperty(name="Walls: Route A", subtype='COLOR', size=4, default=(0.55,0.30,0.95,1.0), min=0, max=1)
    col_route_b: FloatVectorProperty(name="Walls: Route B", subtype='COLOR', size=4, default=(1.0,0.55,0.20,1.0), min=0, max=1)
    col_intersect: FloatVectorProperty(name="Walls: Intersect", subtype='COLOR', size=4, default=(0.60,0.28,0.18,1.0), min=0, max=1)

    mat_default_name: StringProperty(name="Mat Walls Default", default="MazeWall")
    mat_route_a_name:  StringProperty(name="Mat Walls RouteA", default="MazeRouteA")
    mat_route_b_name:  StringProperty(name="Mat Walls RouteB", default="MazeRouteB")
    mat_inter_name:    StringProperty(name="Mat Walls Inter", default="MazeRouteIntersect")
    mat_floor_name:    StringProperty(name="Mat Floor", default="MazeFloor")

    clear_meshes_first: BoolProperty(name="Clear Existing Meshes", default=True)

    # MSSS config
    starts_count: IntProperty(name="Starts", default=4, min=1, soft_max=24)

    # Cost preset for initial color split on walls (kept for compatibility)
    cost_preset: EnumProperty(name="Default Cost Preset", items=COST_PRESET_ITEMS, default='PURIST')

    # Zone densities (for costs)
    risk_density: FloatProperty(name="Risk Zone Density", default=0.10, min=0.0, max=1.0)
    expensive_density: FloatProperty(name="Expensive Zone Density", default=0.08, min=0.0, max=1.0)
    certainty_density: FloatProperty(name="Certainty Zone Density", default=0.06, min=0.0, max=1.0)

    experiential_trials: IntProperty(name="Experiential Trials", default=600, min=50, soft_max=5000)

    # ===== Path overlays (floor) =====
    include_purist: BoolProperty(name="Draw Purist", default=True)
    include_cautious: BoolProperty(name="Draw Cautious", default=True)
    include_experiential: BoolProperty(name="Draw Experiential", default=True)
    include_utilitarian: BoolProperty(name="Draw Utilitarian", default=True)
    include_faith: BoolProperty(name="Draw Faith", default=True)

    style_col_purist: FloatVectorProperty(name="Purist Color", subtype='COLOR', size=4, default=(0.2,0.7,1.0,1.0), min=0, max=1)
    style_col_cautious: FloatVectorProperty(name="Cautious Color", subtype='COLOR', size=4, default=(1.0,0.4,0.2,1.0), min=0, max=1)
    style_col_experiential: FloatVectorProperty(name="Experiential Color", subtype='COLOR', size=4, default=(1.0,0.8,0.2,1.0), min=0, max=1)
    style_col_utilitarian: FloatVectorProperty(name="Utilitarian Color", subtype='COLOR', size=4, default=(0.3,1.0,0.5,1.0), min=0, max=1)
    style_col_faith: FloatVectorProperty(name="Faith Color", subtype='COLOR', size=4, default=(0.9,0.6,1.0,1.0), min=0, max=1)

    path_tile_size: FloatProperty(name="Path Tile Size", default=0.85, min=0.05,
                                  description="Footprint of each floor path tile (XY).")
    path_tile_height: FloatProperty(name="Path Tile Height", default=0.05, min=0.005,
                                    description="Height of floor path tiles (Z).")
    path_z_offset: FloatProperty(name="Path Z Offset", default=0.03, min=0.0,
                                 description="Lift path tiles slightly above the floor to avoid z-fighting.")
    clear_previous_paths: BoolProperty(name="Clear Old Paths", default=True)

    # Start markers
    start_marker_size: FloatProperty(name="Start Marker Size", default=0.6, min=0.05)
    start_marker_height: FloatProperty(name="Start Marker Height", default=1.2, min=0.05)
    start_colors_use_cycle: BoolProperty(name="Cycle Start Colors", default=True)
    start_color1: FloatVectorProperty(name="Start Color 1", subtype='COLOR', size=4, default=(1.0,0.2,0.2,1.0))
    start_color2: FloatVectorProperty(name="Start Color 2", subtype='COLOR', size=4, default=(0.2,1.0,0.2,1.0))
    start_color3: FloatVectorProperty(name="Start Color 3", subtype='COLOR', size=4, default=(0.2,0.6,1.0,1.0))
    start_color4: FloatVectorProperty(name="Start Color 4", subtype='COLOR', size=4, default=(1.0,0.8,0.2,1.0))
    start_color5: FloatVectorProperty(name="Start Color 5", subtype='COLOR', size=4, default=(1.0,0.4,0.8,1.0))
    start_color6: FloatVectorProperty(name="Start Color 6", subtype='COLOR', size=4, default=(0.2,1.0,1.0,1.0))
    start_color7: FloatVectorProperty(name="Start Color 7", subtype='COLOR', size=4, default=(0.8,0.8,0.8,1.0))
    start_color8: FloatVectorProperty(name="Start Color 8", subtype='COLOR', size=4, default=(0.8,0.5,0.2,1.0))

    # Navigator (unchanged)
    nav_color: FloatVectorProperty(name="Navigator Color", subtype='COLOR', size=4, default=(0.1,0.9,0.1,1.0), min=0, max=1)
    trail_color: FloatVectorProperty(name="Trail Color", subtype='COLOR', size=4, default=(0.1,0.8,0.8,1.0), min=0, max=1)
    nav_size: FloatProperty(name="Navigator Size", default=0.6, min=0.05)
    trail_tile_size: FloatProperty(name="Trail Tile Size", default=0.7, min=0.05)
    trail_tile_height: FloatProperty(name="Trail Tile Height", default=0.2, min=0.01)
    nav_start_frame: IntProperty(name="Start Frame", default=1, min=1)
    nav_step_frames: IntProperty(name="Frames per Step", default=6, min=1)
    trail_grow_frames: IntProperty(name="Trail Grow Frames", default=4, min=1)
    nav_clear_old: BoolProperty(name="Clear Old Navigator", default=True)

# =========================
# Generate + cache (walls still colored by alternating groups just like v1.3.1)
# =========================
def wall_touches(cells, r,c,rows,cols):
    if is_border_cell(r,c,rows,cols): return False
    for dr,dc in ((1,0),(-1,0),(0,1),(0,-1)):
        rr,cc=r+dr,c+dc
        if (rr,cc) in cells: return True
    return False

class MMM_OT_Generate(Operator):
    bl_idname = "mmm.generate"
    bl_label = "Generate Maze (MSSS)"
    bl_description = "Generate a Prim's maze, auto-place starts & one end, color walls by two alternating route groups"

    def execute(self, context):
        global LAST_MAZE_CACHE
        p = context.scene.mmm_props
        rng = random.Random(None if p.randomize else p.seed)

        maze_col = get_maze_collection()
        if p.clear_meshes_first:
            clear_collection_objects(maze_col)
        # Also clear path overlays
        clear_collection_objects(get_paths_collection())

        bitmap, rows, cols, start_open, end_open = prims_maze(p.rows, p.cols, rng)
        carve_loops_with_deadend_guard(
            bitmap, rows, cols, rng,
            p.extra_loop_ratio,
            p.keep_deadend_min_ratio,
            p.keep_deadend_min_count
        )

        end_rc = inward(end_open, rows, cols)

        # Auto-place multiple starts near left half, spaced
        starts=[]
        trials=0
        while len(starts)<p.starts_count and trials<6000:
            trials+=1
            r = rng.randrange(1, rows-1)
            c = rng.randrange(1, max(2, cols//3))
            if bitmap[r][c]: continue
            ok=True
            for sr,sc in starts:
                if abs(sr-r)+abs(sc-c) < max(4, min(rows,cols)//10):
                    ok=False; break
            if ok: starts.append((r,c))
        if not starts:
            starts=[inward(start_open, rows, cols)]

        # Basic single-preset paths just for initial wall split (kept)
        clearance = compute_clearance_score(bitmap)
        rng2 = random.Random(1337)
        risk_mask = sample_zone_mask(bitmap, rng2, p.risk_density, border_margin=2)
        expensive_mask = sample_zone_mask(bitmap, rng2, p.expensive_density, border_margin=2)
        certainty_mask = sample_zone_mask(bitmap, rng2, p.certainty_density, border_margin=2)
        preset = PRESET_DEFS[p.cost_preset]
        params = preset['params']
        algo = preset['algo']
        quick_paths=[]
        for s in starts:
            if algo=='DIJKSTRA':
                path = dijkstra_costed_path(bitmap, s, end_rc, params, clearance, risk_mask, expensive_mask, certainty_mask)
            else:
                path = self_avoiding_meander(bitmap, s, end_rc, rng2, params, clearance, risk_mask, expensive_mask, certainty_mask, trials=p.experiential_trials)
            if path: quick_paths.append(path)

        # Build geometry (walls)
        total_w, total_h = cols*p.cell_w, rows*p.cell_h
        off_x, off_y = -total_w/2 + p.cell_w/2, -total_h/2 + p.cell_h/2

        mat_default = ensure_solid_material(p.mat_default_name, tuple(p.col_default))
        mat_routeA  = ensure_solid_material(p.mat_route_a_name,  tuple(p.col_route_a))
        mat_routeB  = ensure_solid_material(p.mat_route_b_name,  tuple(p.col_route_b))
        mat_inter   = ensure_solid_material(p.mat_inter_name,    tuple(p.col_intersect))
        mat_floor   = ensure_solid_material(p.mat_floor_name,    (0.15,0.15,0.17,1.0))

        routeA_cells=set(); routeB_cells=set()
        for i, path in enumerate(quick_paths):
            target = routeA_cells if (i%2==0) else routeB_cells
            for rc in path: target.add(rc)

        wall_blocks = merge_rectangles(bitmap, rows, cols)
        for (r,c,h,w) in wall_blocks:
            sx, sy = w*p.cell_w, h*p.cell_h
            sz = (p.height_max if p.uniform_height else random.uniform(p.height_min, p.height_max))
            cx = off_x + c*p.cell_w + (w-1)*p.cell_w/2
            cy = -(off_y + r*p.cell_h + (h-1)*p.cell_h/2)

            markA=markB=False
            for rr in range(r, r+h):
                for cc in range(c, c+w):
                    if wall_touches(routeA_cells, rr,cc, rows,cols): markA=True
                    if wall_touches(routeB_cells, rr,cc, rows,cols): markB=True
                if markA and markB: break
            mat = mat_inter if (markA and markB) else (mat_routeA if markA else (mat_routeB if markB else mat_default))

            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, 0.0))
            ob=bpy.context.active_object
            ob.name=f"MazeWall_{r}_{c}_{h}x{w}"
            ob.dimensions=(sx,sy,sz)
            sit_on_ground(ob)
            if ob.data.materials: ob.data.materials[0]=mat
            else: ob.data.materials.append(mat)
            link_exclusive(ob, maze_col)

        if p.make_floor:
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
            floor=bpy.context.active_object
            floor.name="MazeFloor"
            floor.dimensions=(total_w + p.cell_w, total_h + p.cell_h, p.floor_thickness)
            sit_on_ground(floor)
            if floor.data.materials: floor.data.materials[0]=mat_floor
            else: floor.data.materials.append(mat_floor)
            link_exclusive(floor, maze_col)

        # Cache for floor overlays per start
        LAST_MAZE_CACHE = {
            "bitmap": bitmap, "rows": rows, "cols": cols,
            "off_x": off_x, "off_y": off_y, "cell_w": p.cell_w, "cell_h": p.cell_h,
            "start_list": starts, "end_rc": end_rc,
            "clearance": clearance,
            "risk_density": p.risk_density, "expensive_density": p.expensive_density, "certainty_density": p.certainty_density,
            "seed": p.seed, "randomize": p.randomize,
        }

        self.report({'INFO'}, f"Maze {p.rows}x{p.cols} | starts: {len(starts)} (floor paths built separately per start).")
        return {'FINISHED'}

# =========================
# Build per-start, multi-style FLOOR routes
# =========================
def rc_to_world(off_x, off_y, cell_w, cell_h, rc):
    r,c = rc
    return off_x + c*cell_w, -(off_y + r*cell_h)

def style_iter(props):
    # Yield (style_key, include_flag, color, preset_key)
    yield ('PURIST', props.include_purist, props.style_col_purist, 'PURIST')
    yield ('CAUTIOUS', props.include_cautious, props.style_col_cautious, 'CAUTIOUS')
    yield ('EXPERIENTIAL', props.include_experiential, props.style_col_experiential, 'EXPERIENTIAL')
    yield ('UTILITARIAN', props.include_utilitarian, props.style_col_utilitarian, 'UTILITARIAN')
    yield ('FAITH', props.include_faith, props.style_col_faith, 'FAITH')

def start_color_from_index(p, idx):
    colors = [
        p.start_color1, p.start_color2, p.start_color3, p.start_color4,
        p.start_color5, p.start_color6, p.start_color7, p.start_color8
    ]
    if p.start_colors_use_cycle:
        return tuple(colors[idx % len(colors)])
    # If not cycling, just use #1 for all
    return tuple(p.start_color1)

class MMM_OT_BuildFloorRoutes(Operator):
    bl_idname = "mmm.build_floor_routes"
    bl_label = "Build Routes on Floor"
    bl_description = "For a chosen start (or all starts), compute Purist/Cautious/Experiential/Utilitarian/Faith paths and draw colored tiles on the floor"

    start_index: IntProperty(name="Start Index (0..N-1 or -1=All)", default=-1, min=-1)
    clear_before: BoolProperty(name="Clear Old Paths First", default=True)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        global LAST_MAZE_CACHE
        p = context.scene.mmm_props
        cache = LAST_MAZE_CACHE
        if cache is None:
            self.report({'WARNING'}, "Generate a maze first."); return {'CANCELLED'}

        bitmap = cache["bitmap"]
        rows, cols = cache["rows"], cache["cols"]
        starts = cache["start_list"]
        end_rc = cache["end_rc"]
        off_x, off_y = cache["off_x"], cache["off_y"]
        cell_w, cell_h = cache["cell_w"], cache["cell_h"]
        clearance = cache["clearance"]

        rng = random.Random(None if p.randomize else cache.get("seed", 0))
        # Regenerate masks per build for variety but consistent densities
        risk_mask = sample_zone_mask(bitmap, rng, p.risk_density, border_margin=2)
        expensive_mask = sample_zone_mask(bitmap, rng, p.expensive_density, border_margin=2)
        certainty_mask = sample_zone_mask(bitmap, rng, p.certainty_density, border_margin=2)

        starts_range = range(len(starts)) if self.start_index < 0 else [max(0, min(self.start_index, len(starts)-1))]

        paths_col = get_paths_collection()
        if self.clear_before or p.clear_previous_paths:
            clear_collection_objects(paths_col, name_prefixes=("Path_", "StartMarker_"))

        # Materials for styles (shared)
        mat_style = {
            'PURIST': ensure_solid_material("PathStyle_Purist", tuple(p.style_col_purist)),
            'CAUTIOUS': ensure_solid_material("PathStyle_Cautious", tuple(p.style_col_cautious)),
            'EXPERIENTIAL': ensure_solid_material("PathStyle_Experiential", tuple(p.style_col_experiential)),
            'UTILITARIAN': ensure_solid_material("PathStyle_Utilitarian", tuple(p.style_col_utilitarian)),
            'FAITH': ensure_solid_material("PathStyle_Faith", tuple(p.style_col_faith)),
        }

        # Draw start markers first (so you see them even without paths)
        for si in starts_range:
            sr,sc = starts[si]
            sx, sy = rc_to_world(off_x, off_y, cell_w, cell_h, (sr,sc))
            color = start_color_from_index(p, si)
            mat = ensure_solid_material(f"StartColor_{si:02d}", color)
            # Marker: a small pillar (cylinder) to stand out
            try:
                bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=p.start_marker_size/2.0, depth=p.start_marker_height, location=(sx,sy,0))
                mark = bpy.context.active_object
            except:
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sx,sy,0))
                mark = bpy.context.active_object
                mark.dimensions = (p.start_marker_size, p.start_marker_size, p.start_marker_height)
            mark.name = f"StartMarker_{si:02d}"
            sit_on_ground(mark)
            if mark.data.materials: mark.data.materials[0]=mat
            else: mark.data.materials.append(mat)
            link_exclusive(mark, paths_col)

        # Helper to place one path as floor tiles
        def place_path_tiles(path, style_key, si):
            if not path: return
            tile_w = p.path_tile_size
            tile_h = p.path_tile_size
            tile_z = p.path_tile_height
            z_off  = p.path_z_offset
            mat = mat_style[style_key]
            for i, rc in enumerate(path):
                x,y = rc_to_world(off_x, off_y, cell_w, cell_h, rc)
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x,y,0.0))
                tile = bpy.context.active_object
                tile.name = f"Path_{style_key}_S{si:02d}_{i:04d}"
                tile.dimensions = (tile_w, tile_h, tile_z)
                sit_on_ground(tile)
                tile.location.z += z_off  # lift slightly
                if tile.data.materials: tile.data.materials[0]=mat
                else: tile.data.materials.append(mat)
                link_exclusive(tile, paths_col)

        # For each requested start, compute and draw selected styles
        built = 0
        for si in starts_range:
            s = starts[si]
            for style_key, include, color, preset_key in style_iter(p):
                if not include: continue
                preset = PRESET_DEFS[preset_key]
                params = preset['params']
                algo = preset['algo']
                if algo == 'DIJKSTRA':
                    path = dijkstra_costed_path(bitmap, s, end_rc, params, clearance, risk_mask, expensive_mask, certainty_mask)
                else:
                    path = self_avoiding_meander(bitmap, s, end_rc, rng, params, clearance, risk_mask, expensive_mask, certainty_mask, trials=p.experiential_trials)
                place_path_tiles(path, style_key, si)
                built += 1

        self.report({'INFO'}, f"Built floor paths: {built} style-sets over {len(starts_range)} start(s).")
        return {'FINISHED'}

# =========================
# Export (unchanged from v1.3.1)
# =========================
class MMM_OT_ExportMerged(Operator):
    bl_idname = "mmm.export_merged"
    bl_label = "Export: Merge to Single Mesh"
    include_floor: BoolProperty(name="Include Floor", default=True)
    merged_name: StringProperty(name="Merged Name", default="MazeMerged")
    def invoke(self, context, event): return context.window_manager.invoke_props_dialog(self)
    def execute(self, context):
        maze_col=get_maze_collection()
        src=[o for o in maze_col.objects if o.type=='MESH' and (o.name.startswith("MazeWall_") or o.name=="MazeFloor")]
        if not self.include_floor: src=[o for o in src if o.name!="MazeFloor"]
        if not src: self.report({'WARNING'},"No maze meshes found to merge."); return {'CANCELLED'}
        select_only(src); bpy.ops.object.duplicate()
        dups=[o for o in bpy.context.view_layer.objects if o.select_get()]
        if not dups: self.report({'WARNING'}, "Duplication failed."); return {'CANCELLED'}
        bpy.context.view_layer.objects.active=dups[0]
        try: bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        except: pass
        bpy.ops.object.join()
        merged=bpy.context.view_layer.objects.active
        merged.name=self.merged_name
        merged.data=merged.data.copy()
        link_exclusive(merged, maze_col)
        self.report({'INFO'}, f"Merged {len(src)} objects into '{merged.name}'.")
        return {'FINISHED'}

class MMM_OT_ExportFiles(Operator):
    bl_idname = "mmm.export_files"
    bl_label = "Export Maze (OBJ / FBX / GLB)"
    export_format: EnumProperty(
        name="Format",
        items=[('OBJ',"OBJ","Wavefront OBJ"),('FBX',"FBX","Autodesk FBX"),('GLB',"GLB","glTF Binary")],
        default='GLB'
    )
    include_floor: BoolProperty(name="Include Floor", default=True)
    join_mode: EnumProperty(
        name="Export Mode",
        items=[('SEPARATE',"Separate Objects","Export each maze object as-is"),
               ('MERGED',"Single Merged Mesh","Export a temporary joined mesh")],
        default='SEPARATE'
    )
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')
    def invoke(self, context, event):
        ext={ 'OBJ':".obj",'FBX':".fbx",'GLB':".glb"}[self.export_format]
        if not self.filepath: self.filepath=bpy.path.abspath(f"//maze_export{ext}")
        context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}
    def execute(self, context):
        maze_col=get_maze_collection()
        objs=[o for o in maze_col.objects if o.type=='MESH' and (o.name.startswith("MazeWall_") or o.name=="MazeFloor")]
        if not self.include_floor: objs=[o for o in objs if o.name!="MazeFloor"]
        if not objs: self.report({'WARNING'}, "No maze meshes found to export."); return {'CANCELLED'}
        temp=None; export_set=objs
        if self.join_mode=='MERGED':
            select_only(objs); bpy.ops.object.duplicate()
            dups=[o for o in bpy.context.view_layer.objects if o.select_get()]
            if not dups: self.report({'WARNING'}, "Duplication failed."); return {'CANCELLED'}
            bpy.context.view_layer.objects.active=dups[0]
            try: bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            except: pass
            bpy.ops.object.join(); temp=bpy.context.view_layer.objects.active
            temp.name="MazeExport_Temp"; link_exclusive(temp, maze_col); export_set=[temp]
        select_only(export_set)
        fp=bpy.path.abspath(self.filepath); os.makedirs(os.path.dirname(fp), exist_ok=True)
        try:
            if self.export_format=='OBJ': bpy.ops.wm.obj_export(filepath=fp, export_selected_objects=True)
            elif self.export_format=='FBX': bpy.ops.export_scene.fbx(filepath=fp, use_selection=True, apply_scale_options='FBX_SCALE_NONE')
            elif self.export_format=='GLB': bpy.ops.export_scene.gltf(filepath=fp, export_format='GLB', use_selection=True)
        except Exception as e:
            self.report({'ERROR'}, f"Export failed: {e}")
            if temp: select_only([temp]); bpy.ops.object.delete()
            return {'CANCELLED'}
        if temp: select_only([temp]); bpy.ops.object.delete()
        self.report({'INFO'}, f"Exported maze to {fp}")
        return {'FINISHED'}

# =========================
# Navigator (unchanged, animates one chosen start’s route set if you want to adapt later)
# =========================
class MMM_OT_CreateNavigator(Operator):
    bl_idname = "mmm.create_navigator"
    bl_label = "Create Navigator + Trail"
    bl_description = "Animate a navigator along a selected start→end route (uses previously cached quick path set)"
    start_index: IntProperty(name="Start Index", default=0, min=0)
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    def execute(self, context):
        global LAST_MAZE_CACHE
        p = context.scene.mmm_props
        if LAST_MAZE_CACHE is None:
            self.report({'WARNING'}, "Generate a maze first.")
            return {'CANCELLED'}
        cache=LAST_MAZE_CACHE
        # For simplicity, animate along the Purist path computed ad-hoc for this start
        bitmap = cache["bitmap"]; off_x, off_y = cache["off_x"], cache["off_y"]
        cell_w, cell_h = cache["cell_w"], cache["cell_h"]; end_rc = cache["end_rc"]
        starts = cache["start_list"]; idx=max(0, min(self.start_index, len(starts)-1))
        s = starts[idx]
        clearance = cache["clearance"]
        rng = random.Random(None if cache.get("randomize", True) else cache.get("seed", 0))
        risk_mask = sample_zone_mask(bitmap, rng, 0.0); expensive_mask = sample_zone_mask(bitmap, rng, 0.0); certainty_mask = sample_zone_mask(bitmap, rng, 0.0)
        path = dijkstra_costed_path(bitmap, s, end_rc, PRESET_DEFS['PURIST']['params'], clearance, risk_mask, expensive_mask, certainty_mask)
        if not path: self.report({'WARNING'},"No path."); return {'CANCELLED'}

        maze_col=get_maze_collection()
        if p.nav_clear_old:
            old=[o for o in maze_col.objects if o.name.startswith("Navigator_") or o.name.startswith("Trail_")]
            if old: select_only(old); bpy.ops.object.delete()

        mat_nav = ensure_solid_material("MazeNavigator", tuple(p.nav_color))
        mat_trail = ensure_solid_material("MazeTrail", tuple(p.trail_color))

        def rcw(rc): return rc_to_world(off_x, off_y, cell_w, cell_h, rc)

        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,0))
        agent=bpy.context.active_object
        agent.name=f"Navigator_{idx:02d}"
        agent.dimensions=(p.nav_size, p.nav_size, p.nav_size)
        sit_on_ground(agent)
        if agent.data.materials: agent.data.materials[0]=mat_nav
        else: agent.data.materials.append(mat_nav)
        link_exclusive(agent, maze_col)

        f0=p.nav_start_frame; step=max(1,int(p.nav_step_frames))
        for i, rc in enumerate(path):
            x,y=rcw(rc)
            agent.location.x=x; agent.location.y=y
            agent.keyframe_insert(data_path="location", frame=f0+i*step)

        grow=max(1,int(p.trail_grow_frames))
        tile_w=p.trail_tile_size; tile_h=p.trail_tile_size; tile_z=p.trail_tile_height
        for i, rc in enumerate(path):
            x,y=rcw(rc)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x,y,0.0))
            tile=bpy.context.active_object
            tile.name=f"Trail_{idx:02d}_{i:04d}"
            tile.dimensions=(tile_w, tile_h, tile_z)
            sit_on_ground(tile)
            if tile.data.materials: tile.data.materials[0]=mat_trail
            else: tile.data.materials.append(mat_trail)
            link_exclusive(tile, maze_col)
            tile.scale=(0.001,0.001,1.0)
            tile.keyframe_insert(data_path="scale", frame=f0+i*step)
            tile.scale=(1.0,1.0,1.0)
            tile.keyframe_insert(data_path="scale", frame=f0+i*step+grow)

        self.report({'INFO'}, f"Navigator for start #{idx} with {len(path)} steps created.")
        return {'FINISHED'}

# =========================
# UI
# =========================
class MMM_PT_Panel(Panel):
    bl_label = "Mo's Maze Maker"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Mo's Maze Maker"

    def draw(self, context):
        p=context.scene.mmm_props
        layout=self.layout

        box=layout.box(); box.label(text="Maze Size & Seed")
        row=box.row(align=True); row.prop(p,"rows"); row.prop(p,"cols")
        row=box.row(align=True); row.prop(p,"randomize")
        if not p.randomize: row.prop(p,"seed")

        box=layout.box(); box.label(text="Geometry")
        row=box.row(align=True); row.prop(p,"cell_w"); row.prop(p,"cell_h")
        row=box.row(align=True); row.prop(p,"height_min"); row.prop(p,"height_max")
        box.prop(p,"uniform_height")

        box=layout.box(); box.label(text="Loops & Dead-Ends")
        box.prop(p,"extra_loop_ratio")
        row=box.row(align=True); row.prop(p,"keep_deadend_min_ratio"); row.prop(p,"keep_deadend_min_count")

        box=layout.box(); box.label(text="MSSS Setup")
        row=box.row(align=True); row.prop(p,"starts_count")
        box.prop(p, "cost_preset")
        row=box.row(align=True); row.prop(p, "risk_density"); row.prop(p, "expensive_density"); row.prop(p, "certainty_density")
        box.prop(p, "experiential_trials")
        box.label(text="Generate builds walls & caches; floor paths are per-start below.", icon='INFO')

        box=layout.box(); box.label(text="Floor Paths (per start)")
        row=box.row(align=True); row.prop(p,"include_purist"); row.prop(p,"include_cautious"); row.prop(p,"include_experiential")
        row=box.row(align=True); row.prop(p,"include_utilitarian"); row.prop(p,"include_faith")
        row=box.row(align=True); row.prop(p,"path_tile_size"); row.prop(p,"path_tile_height"); row.prop(p,"path_z_offset")
        row=box.row(align=True); row.prop(p,"clear_previous_paths")
        box.prop(p,"style_col_purist"); box.prop(p,"style_col_cautious"); box.prop(p,"style_col_experiential")
        box.prop(p,"style_col_utilitarian"); box.prop(p,"style_col_faith")
        op=box.operator("mmm.build_floor_routes", text="Build Routes on Floor", icon='MOD_BUILD')

        box=layout.box(); box.label(text="Start Markers")
        row=box.row(align=True); row.prop(p,"start_marker_size"); row.prop(p,"start_marker_height")
        row=box.row(align=True); row.prop(p,"start_colors_use_cycle")
        row=box.row(align=True); row.prop(p,"start_color1"); row.prop(p,"start_color2")
        row=box.row(align=True); row.prop(p,"start_color3"); row.prop(p,"start_color4")
        row=box.row(align=True); row.prop(p,"start_color5"); row.prop(p,"start_color6")
        row=box.row(align=True); row.prop(p,"start_color7"); row.prop(p,"start_color8")

        box=layout.box(); box.label(text="Floor & Materials")
        box.prop(p,"make_floor"); box.prop(p,"floor_thickness")
        box.prop(p,"mat_floor_name")
        box.prop(p,"mat_default_name"); box.prop(p,"mat_route_a_name"); box.prop(p,"mat_route_b_name"); box.prop(p,"mat_inter_name")

        layout.separator()
        layout.prop(p,"clear_meshes_first")
        layout.operator("mmm.generate", icon='MESH_CUBE', text="Generate Maze")

        layout.separator()
        row=layout.row(align=True); row.operator("mmm.export_merged", icon='AUTOMERGE_ON')
        box=layout.box(); box.label(text="Export (OBJ / FBX / GLB)")
        box.operator("mmm.export_files", text="Export…", icon='EXPORT')

        layout.separator()
        nav=layout.box(); nav.label(text="Navigator")
        nav.prop(p,"nav_color"); nav.prop(p,"trail_color")
        row=nav.row(align=True); row.prop(p,"nav_size"); row.prop(p,"trail_tile_size")
        row=nav.row(align=True); row.prop(p,"trail_tile_height")
        row=nav.row(align=True); row.prop(p,"nav_start_frame"); row.prop(p,"nav_step_frames")
        nav.prop(p,"trail_grow_frames")
        nav.prop(p,"nav_clear_old")
        nav.operator("mmm.create_navigator", icon='ANIM', text="Create Navigator + Trail")

# =========================
# Register
# =========================
classes=(
    MMM_ColorPreset, MMM_Preferences,
    MMM_Props,
    MMM_OT_Generate,
    MMM_OT_BuildFloorRoutes,
    MMM_OT_ExportMerged, MMM_OT_ExportFiles,
    MMM_OT_SavePreset, MMM_OT_ApplyPreset, MMM_OT_DeletePreset,
    MMM_OT_CreateNavigator,
    MMM_PT_Panel,
)

def register():
    for c in classes: bpy.utils.register_class(c)
    bpy.types.Scene.mmm_props = PointerProperty(type=MMM_Props)

def unregister():
    del bpy.types.Scene.mmm_props
    for c in reversed(classes): bpy.utils.unregister_class(c)

if __name__=="__main__":
    register()
