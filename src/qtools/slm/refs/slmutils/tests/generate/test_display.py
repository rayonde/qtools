import numpy as np
import pytest

from slmutils.generate.display import SUPPORTED_EXTENSIONS, DisplayMask


@pytest.fixture
def default_mask():
    return DisplayMask((120, 100))


def test_display_save_load_supported_extensions(default_mask, tmp_path):
    basepath = tmp_path / "test_display_save_load_png"
    for suffix in SUPPORTED_EXTENSIONS:
        target = basepath.with_suffix(suffix)

        # Save
        mask = default_mask.random()
        mask.save(target)

        # Load
        mask2 = DisplayMask(target)
        assert np.all(mask.array == mask2.array)


def test_display_flat(default_mask):
    mask = default_mask.flat(120)
    assert np.all(mask.array == 120)


def test_display_random(default_mask):
    mask = default_mask.random()
    assert np.unique(mask.array).size > 10


def test_display_binary():
    test_mask = DisplayMask((4, 3))

    # x
    mask = test_mask.binary(2, level1=0, level2=128)
    assert np.all(
        mask.array
        == np.array(
            [
                [0, 128, 0, 128],
                [0, 128, 0, 128],
                [0, 128, 0, 128],
            ]
        )
    )

    # x exact fill
    mask = test_mask.binary((4, 0), level1=0, level2=128)
    assert np.all(
        mask.array
        == np.array(
            [
                [0, 0, 128, 128],
                [0, 0, 128, 128],
                [0, 0, 128, 128],
            ]
        )
    )

    # y
    mask = test_mask.binary((0, 2), level1=0, level2=128)
    assert np.all(
        mask.array
        == np.array(
            [
                [0, 0, 0, 0],
                [128, 128, 128, 128],
                [0, 0, 0, 0],
            ]
        )
    )

    # y overfill
    mask = test_mask.binary((0, 4), level1=0, level2=128)
    assert np.all(
        mask.array
        == np.array(
            [
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [128, 128, 128, 128],
            ]
        )
    )

    # checkerboard
    mask = test_mask.binary((2, 2), level1=20, level2=50)
    assert np.all(
        mask.array
        == np.array(
            [
                [20, 50, 20, 50],
                [50, 20, 50, 20],
                [20, 50, 20, 50],
            ]
        )
    )

    # checkerboard overfill
    mask = test_mask.binary((4, 4), level1=20, level2=50)
    assert np.all(
        mask.array
        == np.array(
            [
                [20, 20, 50, 50],
                [20, 20, 50, 50],
                [50, 50, 20, 20],
            ]
        )
    )


def test_display_copy(default_mask):
    # init
    mask = DisplayMask(default_mask)
    assert mask.array is not default_mask.array

    # init array
    mask = DisplayMask(default_mask.array)
    assert mask.array is not default_mask.array

    # asarray
    array = DisplayMask.asarray(default_mask)
    assert array is not default_mask.array

    # flat
    mask = default_mask.flat(0)
    assert mask.array is not default_mask.array

    # random
    mask = default_mask.random()
    assert mask.array is not default_mask.array

    # add / replace / crop / shift
    int_mask = default_mask.flat(0)
    mask = default_mask.add(int_mask)
    assert mask.array is not default_mask.array
    mask = default_mask.replace(int_mask)
    assert mask.array is not default_mask.array
    mask = default_mask.crop()
    assert mask.array is not default_mask.array
    mask = default_mask.shift()
    assert mask.array is not default_mask.array
    mask = default_mask.flip()
    assert mask.array is not default_mask.array
    mask = default_mask
    mask += int_mask
    assert mask.array is not default_mask.array
    mask = default_mask + int_mask
    assert mask.array is not default_mask.array

    # ndarray addition
    raw_array = default_mask.array
    mask = default_mask + raw_array
    assert mask.array is not default_mask.array
