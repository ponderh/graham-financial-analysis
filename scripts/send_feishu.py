#!/usr/bin/env python3
"""
飞书消息发送脚本（用于发送分析报告摘要）
用法: python3 send_feishu.py "<open_id>" "<消息内容>"
或通过OpenClaw message工具发送，不依赖此脚本
"""
import sys

def send_message(open_id, message):
    """
    实际发送通过OpenClaw的message工具：
    message(action="send", channel="feishu", target="<open_id>", message="...")
    此脚本仅作为参考备用
    """
    print(f"[飞书发送模拟]")
    print(f"目标: {open_id}")
    print(f"内容: {message[:100]}...")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("用法: python3 send_feishu.py '<open_id>' '<消息内容>'")
        sys.exit(1)
    send_message(sys.argv[1], sys.argv[2])
