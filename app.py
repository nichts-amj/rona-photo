"""Windows CLI: default regional hybrid C, with optional model comparison."""
import argparse
import sys
from pathlib import Path

from pipeline.run import run_control


def main() -> int:
    if len(sys.argv) == 1:
        from web_app import main as web_main
        web_main()
        return 0
    parser = argparse.ArgumentParser(description="AI Photo Retouch: default gabungan C, masker area manual.")
    parser.add_argument("--input", type=Path, required=True, help="Foto asli JPEG/PNG, tidak diperkecil.")
    parser.add_argument("--mode", choices=["hybrid-c", "control", "sr2"], default="hybrid-c")
    parser.add_argument("--regions", type=Path, help="Masker C terikat hash foto; sampel lama dikenali otomatis.")
    parser.add_argument("--compare-swin2sr", action="store_true", help="Tambahkan Swin2SR sebagai pembanding C, tidak mengubah hasil default.")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda", help="Perangkat SR; kontrol selalu CPU.")
    parser.add_argument("--tile", type=int, default=128, help="Sisi tile input SR; kelipatan 8, minimum 64.")
    parser.add_argument("--overlap", type=int, default=32)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parent / "outputs")
    args = parser.parse_args()
    if args.mode != "hybrid-c" and (args.regions or args.compare_swin2sr):
        parser.error("--regions dan --compare-swin2sr hanya untuk mode hybrid-c.")
    try:
        if args.mode == "control":
            destination = run_control(args.input, args.output_root)
        elif args.mode == "sr2":
            from pipeline.sr_run import run_sr
            destination = run_sr(args.input, args.output_root, args.device, args.tile, args.overlap)
        else:
            from pipeline.hybrid_run import run_hybrid
            destination = run_hybrid(args.input, args.output_root, args.device, args.tile,
                                     args.overlap, args.regions, args.compare_swin2sr)
    except Exception as error:
        print(f"Gagal: {error}", file=sys.stderr)
        return 1
    print(f"Selesai: mode {args.mode}, tanpa degradasi sintetis pada input.")
    print(f"Hasil: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
