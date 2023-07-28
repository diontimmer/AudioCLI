import torchaudio.transforms as T


def resample(batch, srs, sample_rate):
    aug_tf = T.Resample(srs[0], sample_rate)
    return aug_tf(batch), [sample_rate] * len(batch)


def example_func(batch, srs, param1, param2):
    print(f"Processing with {param1} and {param2}...")
