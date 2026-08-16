"""
意图分类器模块
判断消息意图，决定是否需要发简历/微信
"""

from config import QWEN_API_KEY


class IntentClassifier:
    """意图分类器"""
    
    def __init__(self):
        self.api_key = QWEN_API_KEY
    
    def classify(self, message):
        """分类消息意图
        
        Args:
            message: 消息内容
        
        Returns:
            dict: {
                "intent": "询问详情" | "约面试" | "要简历" | "要微信" | "闲聊",
                "need_resume": bool,
                "need_wechat": bool,
                "confidence": float
            }
        """
        # 简单关键词匹配（快速判断）
        message_lower = message.lower()
        
        # 需要发简历的关键词
        resume_keywords = ["简历", "cv", "履历", "发一下简历", "看看简历"]
        need_resume = any(kw in message_lower for kw in resume_keywords)
        
        # 需要发微信的关键词
        wechat_keywords = ["微信", "加微信", "联系方式", "手机号", "电话"]
        need_wechat = any(kw in message_lower for kw in wechat_keywords)
        
        # 判断意图
        if need_resume:
            intent = "要简历"
        elif need_wechat:
            intent = "要微信"
        elif any(kw in message_lower for kw in ["面试", "聊聊", "方便通话", "约个时间"]):
            intent = "约面试"
        elif any(kw in message_lower for kw in ["介绍", "做什么的", "项目经验", "技术栈"]):
            intent = "询问详情"
        else:
            intent = "闲聊"
        
        return {
            "intent": intent,
            "need_resume": need_resume,
            "need_wechat": need_wechat,
            "confidence": 0.9 if (need_resume or need_wechat) else 0.7
        }
