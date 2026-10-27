from qtools.motor.cli import parse_cli_args


def test_move_target_to_angle() -> None:
    args = parse_cli_args(["move", "1", "to", "2.8"])

    assert args.command == "move"
    assert args.move_action == "to"
    assert args.target == "1"
    assert args.angle == "2.8"


def test_move_target_by_angle() -> None:
    args = parse_cli_args(["move", "alice", "by", "22.5"])

    assert args.command == "move"
    assert args.move_action == "by"
    assert args.target == "alice"
    assert args.angle == "22.5"


def test_move_to_angle_without_target_is_unchanged() -> None:
    args = parse_cli_args(["move", "to", "2.8"])

    assert args.command == "move"
    assert args.move_action == "to"
    assert args.target == "2.8"
    assert args.angle is None


def test_move_to_target_angle_is_unchanged() -> None:
    args = parse_cli_args(["move", "to", "1", "2.8"])

    assert args.command == "move"
    assert args.move_action == "to"
    assert args.target == "1"
    assert args.angle == "2.8"
