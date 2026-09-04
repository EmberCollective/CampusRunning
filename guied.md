# 数据生成后使用指南

下面这篇指南用于指导如何使用导出过后的压缩包，来完成具体的跑步数据

生成的文件已自动包含步频/步数数据。**默认输出 FIT 格式**（`config/default_settings.json` 的 `output_format`，可切回 `tcx`）——Keep 的「运动数据文件导入」不解析 TCX 的任何步频字段，FIT 才能通过步数/步幅校验并正常显示步频、步数与步幅（issue #8 真机验证）。FIT 模式需要安装依赖：`pip install garmin-fit-sdk`

## 下载压缩包到手机，或者发送到手机

通过各种方法将web页面生成的压缩包发送到手机，或者通过手机在局域网内打开该网页导出压缩包

## keep数据导入教程

参考下列图例，进行数据导入

点击 *我的*

![keep数据导入教程](guied_image/01.png)

点击 *总跑步*

![keep数据导入教程](guied_image/02.png)

点击 *上方三个点*

![keep数据导入教程](guied_image/03.png)

点击 *运动数据同步*

![keep数据导入教程](guied_image/04.png)

点击 *运动数据文件导入*

![keep数据导入教程](guied_image/05.png)