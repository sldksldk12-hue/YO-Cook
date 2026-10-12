from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="pablovela5620/epfl-smart-kitchen-av1",
    repo_type="dataset",
    allow_patterns="Public_release_videos/train/YH2002/2023_12_04_10_15_23/videos/*.mp4",  # 이 폴더 영상만
    local_dir="datasets/epfl",
)
print("완료")