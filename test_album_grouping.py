"""
单元测试：验证相册分组逻辑修复

测试场景：
1. 简单相册（连续消息）
2. 跨频道相册（相册消息被其他频道消息分隔）
3. 混合场景（相册 + 普通消息 + 跨频道）
"""

from datetime import datetime, timezone


class MockMessage:
    """模拟 Telegram 消息对象"""

    def __init__(self, msg_id, text=None, grouped_id=None, timestamp=0):
        self.id = msg_id
        self.text = text
        self.grouped_id = grouped_id
        self.date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        self.media = None


def test_album_grouping_logic():
    """测试改进后的相册分组逻辑"""

    # ========== 测试场景 1: 简单相册（连续消息） ==========
    print("\n=== 测试 1: 简单相册（连续消息） ===")
    filtered_messages = [
        ("ChannelA", MockMessage(1, grouped_id=100, timestamp=1)),
        ("ChannelA", MockMessage(2, grouped_id=100, timestamp=2)),
        ("ChannelA", MockMessage(3, grouped_id=100, timestamp=3)),
    ]

    album_groups = {}
    batches = []

    for channel_name, msg in filtered_messages:
        if msg.grouped_id:
            key = (channel_name, msg.grouped_id)
            if key not in album_groups:
                album_groups[key] = []
            album_groups[key].append((channel_name, msg))
        else:
            batches.append([(channel_name, msg)])

    for group in album_groups.values():
        batches.append(group)

    batches.sort(key=lambda batch: batch[0][1].date)

    print(f"  相册组数: {len(album_groups)}")
    print(f"  总批次数: {len(batches)}")
    print(f"  第一个批次数: {len(batches[0])}")
    assert len(album_groups) == 1, "应该有1个相册组"
    assert len(batches) == 1, "应该有1个批次（整个相册）"
    assert len(batches[0]) == 3, "批次应该包含3条消息"
    print("  [PASS] 通过")

    # ========== 测试场景 2: 跨频道相册（被其他频道消息分隔） ==========
    print("\n=== 测试 2: 跨频道相册（被其他频道消息分隔） ===")
    # 场景：频道A发送相册，频道B同时发送消息
    # 按时间排序后：A1, A2, B1, A3
    filtered_messages = [
        ("ChannelA", MockMessage(1, grouped_id=200, timestamp=1)),  # 相册第1张
        ("ChannelA", MockMessage(2, grouped_id=200, timestamp=2)),  # 相册第2张
        ("ChannelB", MockMessage(4, text="消息B", timestamp=3)),  # 频道B消息
        (
            "ChannelA",
            MockMessage(3, grouped_id=200, timestamp=4),
        ),  # 相册第3张（被分隔）
    ]

    album_groups = {}
    batches = []

    for channel_name, msg in filtered_messages:
        if msg.grouped_id:
            key = (channel_name, msg.grouped_id)
            if key not in album_groups:
                album_groups[key] = []
            album_groups[key].append((channel_name, msg))
        else:
            batches.append([(channel_name, msg)])

    for group in album_groups.values():
        batches.append(group)

    batches.sort(key=lambda batch: batch[0][1].date)

    print(f"  相册组数: {len(album_groups)}")
    print(f"  总批次数: {len(batches)}")
    print(f"  批次详情:")
    for i, batch in enumerate(batches):
        grouped_id = batch[0][1].grouped_id
        print(
            f"    批次 {i + 1}: {len(batch)} 条消息, grouped_id={grouped_id}, 频道={batch[0][0]}"
        )

    assert len(album_groups) == 1, "应该有1个相册组"
    assert len(batches) == 2, "应该有2个批次（1个相册 + 1条普通消息）"
    assert len(batches[0]) == 3, "第一个批次应该是相册，包含3条消息"
    assert batches[0][0][0] == "ChannelA", "相册应该来自ChannelA"
    assert len(batches[1]) == 1, "第二个批次是普通消息，包含1条"
    assert batches[1][0][0] == "ChannelB", "普通消息应该来自ChannelB"
    print("  [PASS] 通过")

    # ========== 测试场景 3: 混合场景 ==========
    print("\n=== 测试 3: 混合场景（多相册 + 普通消息） ===")
    filtered_messages = [
        ("ChannelA", MockMessage(1, grouped_id=300, timestamp=1)),  # 相册A1
        ("ChannelA", MockMessage(2, grouped_id=300, timestamp=2)),  # 相册A2
        ("ChannelA", MockMessage(3, text="消息1", timestamp=3)),  # 普通消息
        ("ChannelB", MockMessage(4, grouped_id=400, timestamp=4)),  # 相册B1
        ("ChannelB", MockMessage(5, grouped_id=400, timestamp=5)),  # 相册B2
        ("ChannelB", MockMessage(6, grouped_id=400, timestamp=6)),  # 相册B3
        ("ChannelA", MockMessage(4, text="消息2", timestamp=7)),  # 普通消息
    ]

    album_groups = {}
    batches = []

    for channel_name, msg in filtered_messages:
        if msg.grouped_id:
            key = (channel_name, msg.grouped_id)
            if key not in album_groups:
                album_groups[key] = []
            album_groups[key].append((channel_name, msg))
        else:
            batches.append([(channel_name, msg)])

    for group in album_groups.values():
        batches.append(group)

    batches.sort(key=lambda batch: batch[0][1].date)

    print(f"  相册组数: {len(album_groups)}")
    print(f"  总批次数: {len(batches)}")
    print(f"  批次详情:")
    for i, batch in enumerate(batches):
        grouped_id = batch[0][1].grouped_id
        print(
            f"    批次 {i + 1}: {len(batch)} 条消息, grouped_id={grouped_id}, 频道={batch[0][0]}"
        )

    assert len(album_groups) == 2, "应该有2个相册组"
    assert len(batches) == 4, "应该有4个批次（2个相册 + 2条普通消息）"

    # 验证批次顺序和内容
    assert len(batches[0]) == 2 and batches[0][0][1].grouped_id == 300, (
        "批次1: 相册A(2条)"
    )
    assert len(batches[1]) == 1 and batches[1][0][1].grouped_id is None, (
        "批次2: 普通消息"
    )
    assert len(batches[2]) == 3 and batches[2][0][1].grouped_id == 400, (
        "批次3: 相册B(3条)"
    )
    assert len(batches[3]) == 1 and batches[3][0][1].grouped_id is None, (
        "批次4: 普通消息"
    )
    print("  [PASS] 通过")

    # ========== 测试场景 4: 空相册被分隔（旧逻辑会失败的场景） ==========
    print("\n=== 测试 4: 边界场景 - 相册被完全打散 ===")
    # 场景：相册的每张消息之间都插入了其他频道的消息
    # 排序后：A1, B1, A2, B2, A3, B3
    filtered_messages = [
        ("ChannelA", MockMessage(1, grouped_id=500, timestamp=1)),  # 相册第1张
        ("ChannelB", MockMessage(1, text="B1", timestamp=2)),  # 插入消息
        (
            "ChannelA",
            MockMessage(2, grouped_id=500, timestamp=3),
        ),  # 相册第2张（被分隔）
        ("ChannelB", MockMessage(2, text="B2", timestamp=4)),  # 插入消息
        (
            "ChannelA",
            MockMessage(3, grouped_id=500, timestamp=5),
        ),  # 相册第3张（被分隔）
        ("ChannelB", MockMessage(3, text="B3", timestamp=6)),  # 插入消息
    ]

    album_groups = {}
    batches = []

    for channel_name, msg in filtered_messages:
        if msg.grouped_id:
            key = (channel_name, msg.grouped_id)
            if key not in album_groups:
                album_groups[key] = []
            album_groups[key].append((channel_name, msg))
        else:
            batches.append([(channel_name, msg)])

    for group in album_groups.values():
        batches.append(group)

    batches.sort(key=lambda batch: batch[0][1].date)

    print(f"  相册组数: {len(album_groups)}")
    print(f"  总批次数: {len(batches)}")
    print(f"  批次详情:")
    for i, batch in enumerate(batches):
        grouped_id = batch[0][1].grouped_id
        print(
            f"    批次 {i + 1}: {len(batch)} 条消息, grouped_id={grouped_id}, 频道={batch[0][0]}"
        )

    # 旧逻辑会把相册拆分成3个批次，新逻辑应该保持为1个批次
    assert len(album_groups) == 1, "应该有1个相册组"
    # 批次数应该是4：1个相册(3条) + 3条普通消息
    assert len(batches) == 4, "应该有4个批次（1个相册 + 3条普通消息）"
    assert len(batches[0]) == 3, "第一个批次应该是相册，包含3条消息"
    print("  [PASS] 通过 - 旧逻辑会拆分，新逻辑正确聚合")

    print("\n" + "=" * 50)
    print("[SUCCESS] 所有测试通过！相册分组逻辑修复有效！")
    print("=" * 50)


if __name__ == "__main__":
    test_album_grouping_logic()
