import asyncio
from pipelines.script2video_pipeline import Script2VideoPipeline


# 取「引子」部分作为测试场景（Row 5-12，共8个镜头）
# 画面描述已通过 AI 优化，符合 decompose_visual_description() 输入规范
script = """
EXT. 太行山 - 冬日黄昏

极远景俯瞰，太行山山脉连绵起伏，冬日薄雾笼罩山峦，色调苍凉深沉。
摄影机缓缓推近，山间一座青砖黛瓦的旧式院落（八路军总部风格建筑）映入眼帘。

NARRATOR (V.O.)
山西省晋中市左权县，麻田八路军总部旧址静默伫立太行山间，承载着一段烽火荣光。

INT. 窑洞室内 - 夜

近景，1943年冬夜，窑洞室内。一位身着八路军军装的中年男子（国字脸，留短须）
侧坐于书桌旁，油灯摇曳，炭炉散发微弱红光，男子第三次缓缓抬起头，目光落向门口。

NARRATOR (V.O.)
鲜有人知，这里也曾是隐蔽战线的无声战场。1943年1月寒夜，李建国在等一个人。

中景，窑洞走廊，一位穿着八路军干部服的中年男子（戴圆框眼镜，面容精干沉稳）
轻扣门框，油灯光从室内透出照亮其半张脸庞，男子目光坚定地走入室内。

NARRATOR (V.O.)
来人是八路军前总情报处骨干，晋冀鲁豫边区工商管理总局局长王兴让。

近景，窑洞内，两人剪影对坐，油灯投下暖光，背景是深暗窑壁。
摄影机缓缓环绕至左侧男子（年长，留短须）侧面，眼神炯炯，目光中透出不容置疑的坚决。

NARRATOR (V.O.)
那晚，王兴让第一次听到"东款西调"战略，也在李建国眼中看到了不容置疑的坚决。
"""

user_requirement = """
历史纪录片风格，不超过10个镜头。画面庄重沉稳，光线偏暗，营造1940年代抗战年代感。
"""

style = "1940s Chinese historical documentary, cinematic, dark and moody lighting, muted color palette"


async def main():
    pipeline = Script2VideoPipeline.init_from_config(
        config_path="configs/wushengbaozhang_google.yaml")
    await pipeline(script=script, user_requirement=user_requirement, style=style)


if __name__ == "__main__":
    asyncio.run(main())
