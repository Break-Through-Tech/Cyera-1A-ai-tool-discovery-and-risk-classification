"""Compare original, trained and deployed BGE on validation, retaining every vote."""
import argparse
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True, help='Saved experiment run')
    p.add_argument('--output', type=Path, help='New comparison directory; default RUN/validation-full or validation-quick')
    p.add_argument('--batch-size', type=int, default=4, help='Encoding batch size; reduce to 1 for memory')
    p.add_argument('--quick', type=int, default=0, help='First N recorded examples per view; development only')
    args = p.parse_args()
    if args.batch_size < 1 or args.quick < 0:
        p.error('batch-size must be positive and quick nonnegative')
    from finetuning.validation import evaluate_run
    output = args.output or args.run / ('validation-quick' if args.quick else 'validation-full')
    evaluate_run(args.run, output, args.batch_size, args.quick)


if __name__ == '__main__':
    main()
