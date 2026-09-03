"""
ParaView CFF 변환 워커 (pvpython 실행 전용)
Author: 퍼팩트리

GUI(pv_export_gui.py)가 subprocess로 호출하는 백엔드 워커입니다.
일반 사용자가 직접 실행할 수도 있습니다.

기능:
  - CFF(.cas.h5) 로드 후 VTU 또는 VTM으로 저장
  - VTU: Merge Blocks 적용 (단일 unstructured grid)
  - VTM: Merge Blocks 미적용 (multi-block 구조 유지)
  - --list-json: 변수 목록을 JSON으로 출력 (GUI 파싱용)

★ pvpython으로 실행해야 합니다.

실행 예시:
    pvpython pv_export_worker.py --case box.cas.h5 --output out.vtu --vars SV_P,SV_U
    pvpython pv_export_worker.py --case box.cas.h5 --output out.vtm --vars SV_P --format vtm
    pvpython pv_export_worker.py --case box.cas.h5 --list-json
"""
import argparse
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from paraview.simple import *
except ImportError as e:
    print("[ERROR] Cannot import paraview.simple. Run with pvpython.", flush=True)
    print("        Detail:", repr(e), flush=True)
    sys.exit(1)


def get_cell_arrays(source):
    """Cell Data 배열 이름 목록."""
    arrays = []
    info = source.GetCellDataInformation()
    for i in range(info.GetNumberOfArrays()):
        arrays.append(info.GetArray(i).GetName())
    return arrays


def get_point_arrays(source):
    """Point Data 배열 이름 목록."""
    arrays = []
    info = source.GetPointDataInformation()
    for i in range(info.GetNumberOfArrays()):
        arrays.append(info.GetArray(i).GetName())
    return arrays


def load_reader(case_path):
    """CFF 파일을 열고 모든 cell array를 활성화."""
    reader = OpenDataFile(str(case_path))
    if reader is None:
        return None
    for attr in ("CellArrays", "CellArrayStatus", "Cellarrays"):
        if hasattr(reader, attr):
            try:
                prop = getattr(reader, attr)
                if hasattr(prop, "Available"):
                    setattr(reader, attr, prop.Available)
            except Exception:
                pass
    reader.UpdatePipeline()
    return reader


def rename_vtm_inner_files(vtm_path, new_base):
    """VTM 저장 후 내부 DataSet(.vtu 등) 파일명을 통일한다.

    - DataSet이 1개면 <new_base>.vtu
    - 여러 개면 <new_base>_0.vtu, <new_base>_1.vtu ...
    폴더 구조는 그대로 두고 파일명만 바꾸며, .vtm 안의 file 참조도 갱신한다.
    갱신된 상대 경로 목록을 반환한다.
    """
    vtm = Path(vtm_path)
    if not vtm.exists():
        return []
    try:
        tree = ET.parse(str(vtm))
    except Exception as e:
        print("  [WARN] .vtm 파싱 실패, 이름 통일 건너뜀: %s" % str(e)[:60], flush=True)
        return []

    root = tree.getroot()
    datasets = [el for el in root.iter("DataSet") if el.get("file")]
    if not datasets:
        return []

    base_dir = vtm.parent
    n = len(datasets)
    renamed = []
    for i, ds in enumerate(datasets):
        old_rel = ds.get("file")
        old_abs = base_dir / old_rel
        ext = Path(old_rel).suffix or ".vtu"
        sub = Path(old_rel).parent  # 보통 <name>_export (없으면 ".")
        fname = ("%s%s" % (new_base, ext)) if n == 1 else ("%s_%d%s" % (new_base, i, ext))
        new_rel = (sub / fname) if str(sub) not in (".", "") else Path(fname)
        new_abs = base_dir / new_rel
        new_rel_str = str(new_rel).replace("\\", "/")

        if old_abs.resolve() != new_abs.resolve() and old_abs.exists():
            new_abs.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(old_abs), str(new_abs))
        ds.set("file", new_rel_str)
        renamed.append(new_rel_str)

    tree.write(str(vtm), encoding="UTF-8", xml_declaration=True)
    return renamed


def main():
    parser = argparse.ArgumentParser(
        description="ParaView CFF -> VTU/VTM 변환 워커 (pvpython 전용)"
    )
    parser.add_argument("--case", "-c", required=True, type=str,
                        help="CFF case 파일 (.cas.h5)")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="출력 파일 경로 (.vtu 또는 .vtm)")
    parser.add_argument("--format", "-f", type=str, default="auto",
                        choices=["auto", "vtu", "vtm"],
                        help="출력 포맷 (auto=확장자로 판단)")
    parser.add_argument("--vars", "-v", type=str, default=None,
                        help="저장할 변수 (쉼표 구분)")
    parser.add_argument("--all", "-a", action="store_true",
                        help="모든 Cell Data 변수 저장")
    parser.add_argument("--list-json", action="store_true",
                        help="변수 목록을 JSON으로 출력 (GUI용)")
    parser.add_argument("--ascii", action="store_true",
                        help="ASCII 형식 저장")
    parser.add_argument("--inner-name", type=str, default=None,
                        help="VTM 내부 .vtu 파일명 통일 (예: Results). 미지정 시 ParaView 기본 이름 유지")
    args = parser.parse_args()

    case_path = Path(args.case)
    if not case_path.exists():
        print("[ERROR] case 파일 없음: %s" % case_path, flush=True)
        sys.exit(1)

    # ==========================================================
    # --list-json 모드: 변수 목록만 JSON으로 출력
    # ==========================================================
    if args.list_json:
        reader = load_reader(case_path)
        if reader is None:
            # 에러 JSON도 마커로 감싸 GUI가 에러 분기로 인식하도록
            print("###JSON_START###", flush=True)
            print(json.dumps({"error": "Cannot open file"}), flush=True)
            print("###JSON_END###", flush=True)
            sys.exit(1)
        # VTU 관점(merge 후)의 cell arrays를 기준으로 제공
        merged = MergeBlocks(Input=reader)
        merged.UpdatePipeline()
        cell_arrays = get_cell_arrays(merged)
        point_arrays = get_point_arrays(merged)
        # JSON 출력 (GUI가 파싱)
        result = {
            "cell_arrays": cell_arrays,
            "point_arrays": point_arrays,
            "case_file": str(case_path),
            "case_size_mb": round(case_path.stat().st_size / 1024**2, 2),
        }
        # 마커로 감싸서 GUI가 정확히 추출하도록
        print("###JSON_START###", flush=True)
        print(json.dumps(result), flush=True)
        print("###JSON_END###", flush=True)
        Delete(merged)
        Delete(reader)
        sys.exit(0)

    # ==========================================================
    # 변환 모드
    # ==========================================================
    if args.output is None:
        print("[ERROR] --output이 필요합니다.", flush=True)
        sys.exit(1)

    output_path = Path(args.output)

    # 포맷 결정
    if args.format == "auto":
        ext = output_path.suffix.lower()
        out_format = "vtm" if ext == ".vtm" else "vtu"
    else:
        out_format = args.format

    print("[1] 입력 파일 검증", flush=True)
    print("  [OK] %s (%.2f MB)" % (case_path.name, case_path.stat().st_size / 1024**2), flush=True)
    name = case_path.name
    if name.lower().endswith(".cas.h5"):
        dat_path = case_path.with_name(name[:-len(".cas.h5")] + ".dat.h5")
    else:
        dat_path = None
    if dat_path and dat_path.exists():
        print("  [OK] %s (%.2f MB)" % (dat_path.name, dat_path.stat().st_size / 1024**2), flush=True)

    print("[PROGRESS] 10", flush=True)

    # ==========================================================
    # CFF 로드
    # ==========================================================
    print("[2] CFF 파일 로딩 중...", flush=True)
    start = time.time()
    reader = load_reader(case_path)
    if reader is None:
        print("[ERROR] 파일을 열 수 없습니다.", flush=True)
        sys.exit(1)
    print("  [OK] 로딩 완료 (%.2f초)" % (time.time() - start), flush=True)
    print("[PROGRESS] 40", flush=True)

    # ==========================================================
    # 포맷별 처리: VTU는 Merge Blocks, VTM은 원본 유지
    # ==========================================================
    if out_format == "vtu":
        print("[3] Merge Blocks 적용 중 (VTU)...", flush=True)
        target = MergeBlocks(Input=reader)
        target.UpdatePipeline()
        print("  [OK] Merge Blocks 완료", flush=True)
    else:
        print("[3] Merge Blocks 생략 (VTM: multi-block 유지)", flush=True)
        target = reader
    print("[PROGRESS] 60", flush=True)

    # ==========================================================
    # 변수 확인
    # ==========================================================
    cell_arrays = get_cell_arrays(target)
    if len(cell_arrays) == 0:
        print("[WARN] Cell Data가 없습니다.", flush=True)

    # 저장할 변수 결정
    if args.all:
        selected = cell_arrays
        print("[4] 모든 Cell Data %d개 선택" % len(selected), flush=True)
    elif args.vars:
        requested = [v.strip() for v in args.vars.split(",") if v.strip()]
        selected = [v for v in requested if v in cell_arrays]
        invalid = [v for v in requested if v not in cell_arrays]
        print("[4] 선택 변수: %s" % selected, flush=True)
        if invalid:
            print("[WARN] 없는 변수: %s" % invalid, flush=True)
        if not selected:
            print("[ERROR] 유효한 변수가 없습니다.", flush=True)
            sys.exit(1)
    else:
        print("[ERROR] --vars 또는 --all이 필요합니다.", flush=True)
        sys.exit(1)

    print("[PROGRESS] 70", flush=True)

    # ==========================================================
    # 출력 폴더 준비 + 저장
    # ==========================================================
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 이전 실행의 잔존 .vtm/.vtu 파일 제거 (마지막 exists() 판정이 이번 실행만 반영하도록)
    # VTM 하위 폴더는 건드리지 않고 .vtm/.vtu 파일 자체만 삭제한다.
    if output_path.exists():
        try:
            output_path.unlink()
        except OSError as e:
            print("[WARN] 기존 출력 파일 삭제 실패: %s" % str(e)[:60], flush=True)

    print("[5] %s 저장 중: %s" % (out_format.upper(), output_path.name), flush=True)
    save_start = time.time()

    # 변수 선택이 실제로 적용되었는지 여부(폴백 저장 시 False)
    selection_applied = True

    if out_format == "vtu":
        # VTU: DataMode 사용
        data_mode = "Ascii" if args.ascii else "Appended"
        SaveData(
            str(output_path),
            proxy=target,
            ChooseArraysToWrite=1,
            PointDataArrays=[],
            CellDataArrays=selected,
            FieldDataArrays=[],
            DataMode=data_mode,
        )
    else:
        # VTM: Multi-block writer. ChooseArraysToWrite + CellDataArrays
        # VTM writer는 DataMode가 없을 수 있으므로 방어적으로 처리
        if args.ascii:
            print("[WARN] --ascii는 VTM 저장에서 지원되지 않아 무시됩니다.", flush=True)
        try:
            SaveData(
                str(output_path),
                proxy=target,
                ChooseArraysToWrite=1,
                PointDataArrays=[],
                CellDataArrays=selected,
                FieldDataArrays=[],
            )
        except Exception as e:
            # 일부 옵션 미지원 시 최소 옵션으로 재시도 (전체 배열이 저장됨)
            print("  [WARN] 옵션 일부 미지원, 기본 저장 시도: %s" % str(e)[:60], flush=True)
            print("[WARN] 변수 선택이 적용되지 않았습니다 — 모든 배열이 저장됩니다.", flush=True)
            selection_applied = False
            SaveData(str(output_path), proxy=target)

        # VTM 내부 .vtu 파일명 통일 (예: Results.vtu)
        if args.inner_name:
            renamed = rename_vtm_inner_files(output_path, args.inner_name)
            if renamed:
                print("  [OK] 내부 파일명 통일 (%d개): %s" % (
                    len(renamed), ", ".join(Path(r).name for r in renamed)), flush=True)

    save_elapsed = time.time() - save_start
    print("[PROGRESS] 95", flush=True)

    # ==========================================================
    # 정리 및 보고
    # ==========================================================
    if out_format == "vtu":
        Delete(target)
    Delete(reader)

    # VTM은 .vtm + 하위 폴더가 생성됨
    if output_path.exists():
        size_mb = output_path.stat().st_size / 1024**2
        total = time.time() - start
        print("[완료] 변환 성공", flush=True)
        print("  파일: %s" % output_path.name, flush=True)
        print("  크기: %.2f MB" % size_mb, flush=True)
        print("  포맷: %s" % out_format.upper(), flush=True)
        if selection_applied:
            print("  변수: %d개 (Cell Data)" % len(selected), flush=True)
        else:
            print("  변수: 전체 배열 (폴백 저장 — 선택 미적용)", flush=True)
        print("  저장 시간: %.2f초" % save_elapsed, flush=True)
        print("  전체 시간: %.2f초" % total, flush=True)
        print("  위치: %s" % output_path.resolve(), flush=True)
        print("[PROGRESS] 100", flush=True)
        print("[SUCCESS]", flush=True)
    else:
        print("[ERROR] 파일 생성 실패: %s" % output_path, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
