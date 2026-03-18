import addon_utils
import argparse
import math
import os
import sys
from collections import Counter

import bpy
from mathutils import Vector


FILES = "abcdefgh"
RANKS = "12345678"
STARTING_COUNTS = {
    "w": Counter({"pawn": 8, "rook": 2, "knight": 2, "bishop": 2, "queen": 1, "king": 1}),
    "b": Counter({"pawn": 8, "rook": 2, "knight": 2, "bishop": 2, "queen": 1, "king": 1}),
}
PIECE_TYPES = {
    "p": "pawn",
    "r": "rook",
    "n": "knight",
    "b": "bishop",
    "q": "queen",
    "k": "king",
}
PIECE_CHARS = {value: key for key, value in PIECE_TYPES.items()}
BOARD_SQUARE = 1.0
BOARD_HALF = 3.5
BOARD_THICKNESS = 0.28
BOARD_MARGIN = 0.55


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument("--before-fen", required=True)
    parser.add_argument("--after-fen", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--seconds", type=float, default=3.5)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--engine", default="BLENDER_EEVEE")
    parser.add_argument("--asset-root", default="/workspace/assets/source/chess-3d-models")
    return parser.parse_args(argv)


def parse_fen(fen):
    fields = fen.strip().split()
    if len(fields) < 2:
        raise ValueError(f"Invalid FEN: {fen}")
    placement = fields[0]
    active = fields[1]
    rows = placement.split("/")
    if len(rows) != 8:
        raise ValueError(f"Invalid FEN board rows: {fen}")

    board = {}
    for row_index, row in enumerate(rows):
        rank = 8 - row_index
        file_index = 0
        for char in row:
            if char.isdigit():
                file_index += int(char)
                continue
            if file_index > 7:
                raise ValueError(f"Invalid FEN placement overflow: {fen}")
            color = "w" if char.isupper() else "b"
            piece_type = PIECE_TYPES[char.lower()]
            square = f"{FILES[file_index]}{rank}"
            board[square] = {"color": color, "type": piece_type}
            file_index += 1
        if file_index != 8:
            raise ValueError(f"Invalid FEN row width: {fen}")
    return {"board": board, "active": active}


def piece_key(piece):
    if piece is None:
        return None
    return (piece["color"], piece["type"])


def diff_squares(before_board, after_board):
    changed = []
    for square in [f"{file}{rank}" for rank in RANKS for file in FILES]:
        if piece_key(before_board.get(square)) != piece_key(after_board.get(square)):
            changed.append(square)
    return changed


def detect_move(before, after):
    before_board = before["board"]
    after_board = after["board"]
    mover = before["active"]

    mover_changed_before = [
        sq
        for sq, piece in before_board.items()
        if piece["color"] == mover and piece_key(after_board.get(sq)) != piece_key(piece)
    ]
    mover_changed_after = [
        sq
        for sq, piece in after_board.items()
        if piece["color"] == mover and piece_key(before_board.get(sq)) != piece_key(piece)
    ]
    opponent_removed = [
        sq
        for sq, piece in before_board.items()
        if piece["color"] != mover and sq not in after_board
    ]

    if len(mover_changed_before) == 2 and len(mover_changed_after) == 2:
        king_from = next(sq for sq in mover_changed_before if before_board[sq]["type"] == "king")
        king_to = next(sq for sq in mover_changed_after if after_board[sq]["type"] == "king")
        rook_from = next(sq for sq in mover_changed_before if before_board[sq]["type"] == "rook")
        rook_to = next(sq for sq in mover_changed_after if after_board[sq]["type"] == "rook")
        return {
            "type": "castle",
            "mover": mover,
            "from": king_from,
            "to": king_to,
            "rook_from": rook_from,
            "rook_to": rook_to,
            "capture_square": None,
        }

    if len(mover_changed_before) != 1 or len(mover_changed_after) != 1:
        changed = diff_squares(before_board, after_board)
        raise ValueError(f"Unsupported move diff between FENs: {changed}")

    from_sq = mover_changed_before[0]
    to_sq = mover_changed_after[0]
    moving_before = before_board[from_sq]
    moving_after = after_board[to_sq]
    capture_square = None
    move_type = "move"

    if to_sq in before_board and before_board[to_sq]["color"] != mover:
        capture_square = to_sq
        move_type = "capture"
    elif opponent_removed:
        capture_square = opponent_removed[0]
        move_type = "capture"

    if moving_before["type"] == "pawn" and moving_after["type"] != "pawn":
        move_type = "promotion"

    return {
        "type": move_type,
        "mover": mover,
        "from": from_sq,
        "to": to_sq,
        "capture_square": capture_square,
        "promotion_to": moving_after["type"] if move_type == "promotion" else None,
    }


def square_to_xy(square):
    file_index = FILES.index(square[0])
    rank_index = int(square[1]) - 1
    x = (file_index - BOARD_HALF) * BOARD_SQUARE
    y = (rank_index - BOARD_HALF) * BOARD_SQUARE
    return Vector((x, y, 0.0))


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)
    for block_group in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.lights,
        bpy.data.images,
        bpy.data.curves,
    ):
        for block in list(block_group):
            if block.users == 0:
                block_group.remove(block)


def ensure_output_dir(path):
    os.makedirs(path, exist_ok=True)


def set_engine(scene, engine_name, samples):
    supported = {item.identifier for item in scene.bl_rna.properties["render"].fixed_type.properties["engine"].enum_items}
    if engine_name not in supported:
        if "BLENDER_EEVEE_NEXT" in supported:
            engine_name = "BLENDER_EEVEE_NEXT"
        elif "BLENDER_EEVEE" in supported:
            engine_name = "BLENDER_EEVEE"
        else:
            engine_name = "CYCLES"

    scene.render.engine = engine_name
    if scene.render.engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = samples
        scene.cycles.preview_samples = max(8, samples // 2)
    elif hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = samples
        scene.eevee.taa_samples = max(8, samples // 2)


def make_material(name, base_color, metallic=0.0, roughness=0.45):
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = base_color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return material


def assign_material(obj, material):
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)


def set_origin_to_geometry(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")


def apply_transform(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def shade_smooth(obj, levels=1):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.shade_smooth()
    modifier = obj.modifiers.new(name="Subdivision", type="SUBSURF")
    modifier.levels = levels
    modifier.render_levels = levels


def import_stl(filepath, collection):
    addon_utils.enable("io_mesh_stl", default_set=False)
    existing = set(bpy.data.objects.keys())
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=filepath)
    else:
        bpy.ops.import_mesh.stl(filepath=filepath)
    imported = [obj for obj in bpy.data.objects if obj.name not in existing]
    if not imported:
        raise RuntimeError(f"Failed to import STL: {filepath}")
    for obj in imported:
        if obj.data:
            obj.data = obj.data.copy()
        for parent_collection in list(obj.users_collection):
            parent_collection.objects.unlink(obj)
        collection.objects.link(obj)
    return imported


def append_blend_objects(filepath, object_names):
    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        data_to.objects = object_names
    objects = []
    for obj in data_to.objects:
        if obj is None:
            continue
        bpy.context.scene.collection.objects.link(obj)
        objects.append(obj)
    return objects


def join_objects(objects, name):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    merged = objects[0]
    merged.name = name
    if merged.data:
        merged.data = merged.data.copy()
    return merged


def normalize_height(obj, target_height):
    set_origin_to_geometry(obj)
    current = obj.dimensions.z or 1.0
    scale = target_height / current
    obj.scale = (scale, scale, scale)
    apply_transform(obj)
    set_origin_to_geometry(obj)
    obj.location.z = obj.dimensions.z / 2.0


def primitive_cylinder(name, radius, depth, location):
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=radius, depth=depth, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def primitive_uv_sphere(name, radius, location):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=radius, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def primitive_cube(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def make_king(collection):
    parts = [
        primitive_cylinder("king_base", 0.38, 0.20, (0, 0, 0.10)),
        primitive_cylinder("king_body", 0.23, 0.92, (0, 0, 0.56)),
        primitive_uv_sphere("king_head", 0.22, (0, 0, 1.12)),
        primitive_cube("king_cross_v", 0.08, (0, 0, 1.42)),
        primitive_cube("king_cross_h", 0.08, (0, 0, 1.42)),
    ]
    parts[3].scale = (0.35, 0.35, 1.0)
    parts[4].scale = (0.85, 0.35, 0.35)
    for obj in parts:
        apply_transform(obj)
        for parent_collection in list(obj.users_collection):
            parent_collection.objects.unlink(obj)
        collection.objects.link(obj)
    king = join_objects(parts, "king_proto")
    normalize_height(king, 1.85)
    return king


def make_queen(collection):
    parts = [
        primitive_cylinder("queen_base", 0.38, 0.20, (0, 0, 0.10)),
        primitive_cylinder("queen_body", 0.23, 0.90, (0, 0, 0.55)),
        primitive_cylinder("queen_collar", 0.28, 0.24, (0, 0, 1.02)),
        primitive_cylinder("queen_top", 0.12, 0.10, (0, 0, 1.20)),
        primitive_uv_sphere("queen_jewel", 0.09, (0, 0, 1.34)),
    ]
    for obj in parts:
        for parent_collection in list(obj.users_collection):
            parent_collection.objects.unlink(obj)
        collection.objects.link(obj)
    queen = join_objects(parts, "queen_proto")
    normalize_height(queen, 1.70)
    return queen


def make_board_base(_asset_root, collection, wood_material):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, -0.02))
    outer = bpy.context.active_object
    outer.name = "board_base"
    outer.scale = (9.85, 9.85, 0.36)
    apply_transform(outer)
    shade_smooth(outer, levels=1)
    assign_material(outer, wood_material)
    for parent_collection in list(outer.users_collection):
        parent_collection.objects.unlink(outer)
    collection.objects.link(outer)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, BOARD_THICKNESS / 2.0))
    inset = bpy.context.active_object
    inset.name = "board_inset"
    inset.scale = (9.15, 9.15, 0.10)
    apply_transform(inset)
    assign_material(inset, wood_material)
    for parent_collection in list(inset.users_collection):
        parent_collection.objects.unlink(inset)
    collection.objects.link(inset)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, BOARD_THICKNESS + 0.01))
    top = bpy.context.active_object
    top.name = "board_playfield"
    top.scale = (8.25, 8.25, 0.035)
    apply_transform(top)
    assign_material(top, wood_material)
    for parent_collection in list(top.users_collection):
        parent_collection.objects.unlink(top)
    collection.objects.link(top)

    for index, (x, y, sx, sy) in enumerate(
        (
            (0.0, -5.35, 4.65, 0.42),
            (0.0, 5.35, 4.65, 0.42),
            (-5.35, 0.0, 0.42, 4.65),
            (5.35, 0.0, 0.42, 4.65),
        )
    ):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, 0.10))
        rail = bpy.context.active_object
        rail.name = f"board_rail_{index}"
        rail.scale = (sx, sy, 0.16)
        apply_transform(rail)
        assign_material(rail, wood_material)
        for parent_collection in list(rail.users_collection):
            parent_collection.objects.unlink(rail)
        collection.objects.link(rail)

    for index, x in enumerate((-8.85, 8.85)):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, 0.0, 0.02))
        tray = bpy.context.active_object
        tray.name = f"capture_tray_{index}"
        tray.scale = (0.62, 3.10, 0.06)
        apply_transform(tray)
        assign_material(tray, wood_material)
        for parent_collection in list(tray.users_collection):
            parent_collection.objects.unlink(tray)
        collection.objects.link(tray)
    return outer


def make_board_squares(collection, light_mat, dark_mat):
    squares = []
    for file_index, file_name in enumerate(FILES):
        for rank_index, rank_name in enumerate(RANKS):
            x = (file_index - BOARD_HALF) * BOARD_SQUARE
            y = (int(rank_name) - 1 - BOARD_HALF) * BOARD_SQUARE
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, BOARD_THICKNESS + 0.05))
            square = bpy.context.active_object
            square.name = f"square_{file_name}{rank_name}"
            square.scale = (0.48, 0.48, 0.028)
            apply_transform(square)
            assign_material(square, light_mat if (file_index + rank_index) % 2 == 0 else dark_mat)
            for parent_collection in list(square.users_collection):
                parent_collection.objects.unlink(square)
            collection.objects.link(square)
            squares.append(square)
    return squares


def make_piece_collection():
    collection = bpy.data.collections.new("PiecePrototypes")
    bpy.context.scene.collection.children.link(collection)
    return collection


def load_piece_prototypes(asset_root, white_mat, black_mat):
    collection = make_piece_collection()
    prototypes = {}

    stl_map = {
        "pawn": os.path.join(asset_root, "stl", "pawn.stl"),
        "knight": os.path.join(asset_root, "stl", "horse.stl"),
        "bishop": os.path.join(asset_root, "stl", "elephant.stl"),
        "rook": os.path.join(asset_root, "stl", "root.stl"),
    }
    heights = {"pawn": 1.05, "knight": 1.25, "bishop": 1.35, "rook": 1.20}

    for piece_type, path in stl_map.items():
        imported = import_stl(path, collection)
        proto = join_objects(imported, f"{piece_type}_proto")
        normalize_height(proto, heights[piece_type])
        prototypes[piece_type] = proto

    prototypes["queen"] = make_queen(collection)
    prototypes["king"] = make_king(collection)

    for proto in prototypes.values():
        proto.hide_viewport = True
        proto.hide_render = True
        proto["white_material"] = white_mat.name
        proto["black_material"] = black_mat.name

    return prototypes


def duplicate_piece(proto, piece_id, color, collection):
    obj = proto.copy()
    obj.data = proto.data.copy()
    obj.name = piece_id
    obj.hide_viewport = False
    obj.hide_render = False
    assign_material(obj, bpy.data.materials[proto["white_material"] if color == "w" else proto["black_material"]])
    collection.objects.link(obj)
    return obj


def count_board(board):
    counts = {"w": Counter(), "b": Counter()}
    for piece in board.values():
        counts[piece["color"]][piece["type"]] += 1
    return counts


def captured_piece_list(board):
    current = count_board(board)
    captured = {"w": [], "b": []}
    for color in ("w", "b"):
        missing = STARTING_COUNTS[color] - current[color]
        for piece_type in ("queen", "rook", "bishop", "knight", "pawn"):
            for _ in range(missing[piece_type]):
                captured[color].append(piece_type)
    return captured


def reserve_slot_positions(color, count):
    slots = []
    x_base = 8.88 if color == "b" else -8.88
    y_start = -2.55
    for index in range(count):
        col = index // 5
        row = index % 5
        x = x_base + (0.24 * col if color == "b" else -0.24 * col)
        y = y_start + row * 1.18
        slots.append(Vector((x, y, BOARD_THICKNESS + 0.02)))
    return slots


def style_object(obj, color):
    obj.rotation_euler = (0, 0, 0)
    if color == "b":
        obj.rotation_euler.z = math.pi


def create_piece_instances(scene_collection, prototypes, before_board, after_board, move_info):
    board_objects = {}
    captured_after = captured_piece_list(after_board)
    animated_capture_piece = None
    animated_capture_color = None
    animated_capture_type = None
    if move_info.get("capture_square"):
        captured_piece = before_board.get(move_info["capture_square"])
        if captured_piece:
            animated_capture_color = captured_piece["color"]
            animated_capture_type = captured_piece["type"]

    for index, (square, piece) in enumerate(sorted(before_board.items())):
        obj = duplicate_piece(prototypes[piece["type"]], f"piece_{index}_{square}", piece["color"], scene_collection)
        style_object(obj, piece["color"])
        xy = square_to_xy(square)
        obj.location = Vector((xy.x, xy.y, obj.dimensions.z / 2.0 + BOARD_THICKNESS))
        obj["piece_type"] = piece["type"]
        obj["piece_color"] = piece["color"]
        board_objects[square] = obj

    reserve_objects = []
    reserve_target = None
    for color in ("w", "b"):
        reserve_piece_types = list(captured_after[color])
        slots = reserve_slot_positions(color, len(reserve_piece_types))
        skipped_animated = False
        for piece_type, slot in zip(reserve_piece_types, slots):
            if (
                color == animated_capture_color
                and piece_type == animated_capture_type
                and move_info.get("capture_square")
                and not skipped_animated
            ):
                reserve_target = slot
                skipped_animated = True
                continue
            obj = duplicate_piece(
                prototypes[piece_type],
                f"reserve_{color}_{piece_type}_{len(reserve_objects)}",
                color,
                scene_collection,
            )
            style_object(obj, color)
            obj.scale = (0.38, 0.38, 0.38)
            apply_transform(obj)
            obj.location = Vector((slot.x, slot.y, obj.dimensions.z / 2.0 + slot.z))
            reserve_objects.append(obj)

    if move_info.get("capture_square"):
        animated_capture_piece = board_objects[move_info["capture_square"]]

    return board_objects, reserve_objects, animated_capture_piece, reserve_target


def create_camera_and_lights(scene):
    bpy.ops.object.camera_add(
        location=(7.0, -10.8, 8.9),
        rotation=(math.radians(57), 0.0, math.radians(31)),
    )
    camera = bpy.context.active_object
    camera.data.lens = 44
    scene.camera = camera

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 12))
    sun = bpy.context.active_object
    sun.data.energy = 1.8
    sun.rotation_euler = (math.radians(45), math.radians(0), math.radians(35))

    bpy.ops.object.light_add(type="AREA", location=(-6.5, -7.5, 7.0))
    fill = bpy.context.active_object
    fill.data.energy = 2500
    fill.data.shape = "RECTANGLE"
    fill.data.size = 10
    fill.data.size_y = 6
    fill.rotation_euler = (math.radians(70), 0, math.radians(15))

    bpy.ops.object.light_add(type="AREA", location=(7.2, 5.5, 5.8))
    rim = bpy.context.active_object
    rim.data.energy = 1500
    rim.data.shape = "RECTANGLE"
    rim.data.size = 7
    rim.data.size_y = 4
    rim.rotation_euler = (math.radians(110), 0, math.radians(120))


def create_hand_material():
    return make_material("Hand", (0.16, 0.19, 0.24, 1.0), roughness=0.68)


def create_hand(scene_collection):
    blend_path = "/workspace/assets/source/leapjs-rigged-hand/models/RevampedHand/Leapmotion_Handsolo_Rig_Right.blend"
    armature_obj, mesh_obj = append_blend_objects(
        blend_path,
        ["Leapmotion_Basehand_Rig_Left", "leapmotion_basehand_mesh"],
    )
    for obj in (armature_obj, mesh_obj):
        for parent_collection in list(obj.users_collection):
            if parent_collection != scene_collection:
                parent_collection.objects.unlink(obj)
    if mesh_obj.parent is None:
        mesh_obj.parent = armature_obj
        modifier = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
        modifier.object = armature_obj
    armature_obj.scale = (0.085, 0.085, 0.085)
    armature_obj.rotation_mode = "XYZ"
    mesh_obj.name = "hand_mesh"
    armature_obj.name = "hand_rig"
    return {"rig": armature_obj, "mesh": mesh_obj}


def apply_hand_material(hand, material):
    assign_material(hand["mesh"], material)


def animate_hand_grip(hand, frame, grip, side):
    rig = hand["rig"]
    rig.rotation_euler = (
        math.radians(88),
        0.0,
        0 if side == "w" else math.pi,
    )
    rig.keyframe_insert(data_path="rotation_euler", frame=frame)

    finger_curl = math.radians(18) + math.radians(42) * grip
    fingertip_curl = math.radians(12) + math.radians(28) * grip
    thumb_spread = math.radians(-18 if side == "w" else 18)
    for name, bone in rig.pose.bones.items():
        bone.rotation_mode = "XYZ"
        if name == "Wrist":
            bone.rotation_euler = (0.0, 0.0, 0.0)
        elif name.startswith("Finger_0"):
            idx = int(name[-1])
            bone.rotation_euler = (
                math.radians(6) + grip * math.radians(8),
                thumb_spread * (0.7 if idx == 0 else 0.35),
                math.radians(-10 if side == "w" else 10),
            )
        else:
            depth = int(name[-1])
            curl = finger_curl if depth < 3 else fingertip_curl
            spread_group = int(name.split("_")[1][0]) - 2
            bone.rotation_euler = (
                curl,
                math.radians(spread_group * 3),
                0.0,
            )
        bone.keyframe_insert(data_path="rotation_euler", frame=frame)


def set_keyframe(obj, frame):
    obj.keyframe_insert(data_path="location", frame=frame)
    obj.keyframe_insert(data_path="rotation_euler", frame=frame)


def animate_piece(obj, frames, positions, rotations=None):
    rotations = rotations or [obj.rotation_euler.copy()] * len(frames)
    for frame, pos, rot in zip(frames, positions, rotations):
        obj.location = pos
        obj.rotation_euler = rot
        set_keyframe(obj, frame)


def ease_keyframes():
    if not bpy.context.scene.animation_data:
        return
    action = bpy.context.scene.animation_data.action
    if not action:
        return
    for fcurve in action.fcurves:
        for keyframe in fcurve.keyframe_points:
            keyframe.interpolation = "BEZIER"
            keyframe.handle_left_type = "AUTO_CLAMPED"
            keyframe.handle_right_type = "AUTO_CLAMPED"


def board_height_for(obj):
    return BOARD_THICKNESS + obj.dimensions.z / 2.0


def animate_scene(scene, hand, board_objects, animated_capture_piece, reserve_target, move_info, after_state, fps, seconds):
    total_frames = max(24, int(fps * seconds))
    scene.frame_start = 1
    scene.frame_end = total_frames

    start = 1
    hover = start + int(total_frames * 0.16)
    grip = start + int(total_frames * 0.24)
    lift = start + int(total_frames * 0.38)
    move_mid = start + int(total_frames * 0.62)
    place = start + int(total_frames * 0.78)
    release = start + int(total_frames * 0.86)
    retreat = total_frames

    mover_side = move_info["mover"]
    moving_piece = board_objects[move_info["from"]]
    from_xy = square_to_xy(move_info["from"])
    to_xy = square_to_xy(move_info["to"])
    from_height = board_height_for(moving_piece)
    lift_height = max(from_height + 1.65, 2.2)
    to_height = board_height_for(moving_piece)

    approach_y = from_xy.y - 4.1 if mover_side == "w" else from_xy.y + 4.1
    retreat_y = to_xy.y - 4.7 if mover_side == "w" else to_xy.y + 4.7
    side_sign = -1 if mover_side == "w" else 1

    hand_rig = hand["rig"]
    hand_positions = [
        Vector((from_xy.x - 0.15, approach_y, 3.8)),
        Vector((from_xy.x - 0.08, from_xy.y - 0.16 * side_sign, from_height + 1.20)),
        Vector((from_xy.x - 0.02, from_xy.y - 0.04 * side_sign, from_height + 0.92)),
        Vector((from_xy.x, from_xy.y, lift_height + 0.78)),
        Vector(((from_xy.x + to_xy.x) / 2.0, (from_xy.y + to_xy.y) / 2.0 - 0.18 * side_sign, lift_height + 0.92)),
        Vector((to_xy.x + 0.04, to_xy.y, to_height + 0.98)),
        Vector((to_xy.x + 0.10, to_xy.y + 0.08 * side_sign, to_height + 1.10)),
        Vector((to_xy.x + 0.20, retreat_y, 3.8)),
    ]
    for frame, position in zip((start, hover, grip, lift, move_mid, place, release, retreat), hand_positions):
        hand_rig.location = position
        set_keyframe(hand_rig, frame)

    animate_hand_grip(hand, start, 0.0, mover_side)
    animate_hand_grip(hand, hover, 0.0, mover_side)
    animate_hand_grip(hand, grip, 1.0, mover_side)
    animate_hand_grip(hand, lift, 1.0, mover_side)
    animate_hand_grip(hand, place, 1.0, mover_side)
    animate_hand_grip(hand, release, 0.0, mover_side)
    animate_hand_grip(hand, retreat, 0.0, mover_side)
    for obj in (hand["mesh"], hand["rig"]):
        obj.hide_render = False
        obj.keyframe_insert(data_path="hide_render", frame=release)
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_render", frame=retreat)

    move_vector = to_xy - from_xy
    travel_angle = math.atan2(move_vector.y, move_vector.x) if move_vector.length > 0.001 else 0.0
    base_rot = moving_piece.rotation_euler.copy()
    lift_rot = Vector((math.radians(-8), 0.0, base_rot.z + travel_angle * 0.15))
    place_rot = base_rot.copy()

    animate_piece(
        moving_piece,
        (start, grip, lift, move_mid, place, release, retreat),
        (
            Vector((from_xy.x, from_xy.y, from_height)),
            Vector((from_xy.x, from_xy.y, from_height)),
            Vector((from_xy.x, from_xy.y, lift_height)),
            Vector(((from_xy.x + to_xy.x) / 2.0, (from_xy.y + to_xy.y) / 2.0, lift_height + 0.25)),
            Vector((to_xy.x, to_xy.y, to_height)),
            Vector((to_xy.x, to_xy.y, to_height)),
            Vector((to_xy.x, to_xy.y, to_height)),
        ),
        (base_rot, base_rot, lift_rot, lift_rot, place_rot, place_rot, place_rot),
    )

    if move_info["type"] == "promotion":
        promoted_type = move_info["promotion_to"]
        moving_piece.hide_render = True
        moving_piece.keyframe_insert(data_path="hide_render", frame=release + 1)
        moving_piece.hide_viewport = True
        moving_piece.keyframe_insert(data_path="hide_viewport", frame=release + 1)
        promoted = duplicate_piece(
            bpy.data.objects[f"{promoted_type}_proto"],
            f"promoted_{promoted_type}",
            move_info["mover"],
            bpy.context.scene.collection,
        )
        style_object(promoted, move_info["mover"])
        promoted.location = Vector((to_xy.x, to_xy.y, board_height_for(promoted)))
        promoted.hide_render = True
        promoted.hide_viewport = True
        promoted.keyframe_insert(data_path="hide_render", frame=release)
        promoted.keyframe_insert(data_path="hide_viewport", frame=release)
        promoted.hide_render = False
        promoted.hide_viewport = False
        promoted.keyframe_insert(data_path="hide_render", frame=release + 1)
        promoted.keyframe_insert(data_path="hide_viewport", frame=release + 1)

    if move_info.get("capture_square") and animated_capture_piece and reserve_target:
        capture_height = board_height_for(animated_capture_piece)
        captured_frames = (place - 2, release + 2, retreat)
        animate_piece(
            animated_capture_piece,
            captured_frames,
            (
                Vector((animated_capture_piece.location.x, animated_capture_piece.location.y, capture_height)),
                Vector((animated_capture_piece.location.x + 0.25 * side_sign, animated_capture_piece.location.y, capture_height + 0.4)),
                Vector((reserve_target.x, reserve_target.y, animated_capture_piece.dimensions.z / 2.0 + reserve_target.z)),
            ),
            (
                animated_capture_piece.rotation_euler.copy(),
                Vector((math.radians(50), 0, math.radians(12) * side_sign)),
                animated_capture_piece.rotation_euler.copy(),
            ),
        )

    if move_info["type"] == "castle":
        rook = board_objects[move_info["rook_from"]]
        rook_from = square_to_xy(move_info["rook_from"])
        rook_to = square_to_xy(move_info["rook_to"])
        rook_height = board_height_for(rook)
        animate_piece(
            rook,
            (grip, place, release),
            (
                Vector((rook_from.x, rook_from.y, rook_height)),
                Vector((rook_to.x, rook_to.y, rook_height)),
                Vector((rook_to.x, rook_to.y, rook_height)),
            ),
        )

    ease_keyframes()


def configure_scene(args):
    scene = bpy.context.scene
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.fps = args.fps
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.018, 0.020, 0.025, 1.0)
    bg.inputs["Strength"].default_value = 0.9
    set_engine(scene, args.engine, args.samples)
    scene.render.filepath = os.path.join(args.output_dir, "frame_")
    return scene


def main():
    args = parse_args()
    ensure_output_dir(args.output_dir)
    clear_scene()

    before = parse_fen(args.before_fen)
    after = parse_fen(args.after_fen)
    move_info = detect_move(before, after)

    scene = configure_scene(args)
    create_camera_and_lights(scene)

    white_piece_mat = make_material("WhitePiece", (0.94, 0.92, 0.84, 1.0), roughness=0.38)
    black_piece_mat = make_material("BlackPiece", (0.12, 0.12, 0.15, 1.0), roughness=0.34)
    board_light_mat = make_material("BoardLight", (0.82, 0.73, 0.61, 1.0), roughness=0.58)
    board_dark_mat = make_material("BoardDark", (0.14, 0.10, 0.09, 1.0), roughness=0.64)
    wood_mat = make_material("BoardWood", (0.66, 0.54, 0.40, 1.0), roughness=0.74)
    hand_mat = create_hand_material()

    scene_collection = scene.collection
    make_board_base(args.asset_root, scene_collection, wood_mat)
    make_board_squares(scene_collection, board_light_mat, board_dark_mat)
    prototypes = load_piece_prototypes(args.asset_root, white_piece_mat, black_piece_mat)
    hand = create_hand(scene_collection)
    apply_hand_material(hand, hand_mat)

    board_objects, _reserve_objects, animated_capture_piece, reserve_target = create_piece_instances(
        scene_collection,
        prototypes,
        before["board"],
        after["board"],
        move_info,
    )

    animate_scene(
        scene,
        hand,
        board_objects,
        animated_capture_piece,
        reserve_target,
        move_info,
        after,
        args.fps,
        args.seconds,
    )

    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
