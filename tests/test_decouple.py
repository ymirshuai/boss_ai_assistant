"""循环解耦（run_campaign）签名与委托测试。"""

import inspect

import main


def test_run_campaign_signature():
    params = inspect.signature(main.BOSSAssistant.run_campaign).parameters
    assert "keyword" in params
    assert "target_greet_count" in params
    assert "duration" in params


def test_start_delegates_to_run_campaign():
    # 自动模式 start() 应委托到 run_campaign，而非再写死主循环
    src = inspect.getsource(main.BOSSAssistant.start)
    assert "run_campaign(" in src


def test_campaign_state_fields_exist():
    # __init__ 应初始化供 UI 读取的状态字段
    fields = main.BOSSAssistant.__init__.__code__.co_names
    assert "campaign_keyword" in fields
    assert "campaign_target" in fields
    assert "latest_screenshot_path" in fields


def test_auto_setup_is_lazy():
    # auto_setup 不再在模块顶层执行，避免无设备环境 import 时连接手机
    import ast
    tree = ast.parse(open(main.__file__, encoding="utf-8").read())
    # 顶层（模块作用域）不应出现 auto_setup( 调用
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            name = getattr(func, "id", getattr(func, "attr", ""))
            assert name != "auto_setup"
