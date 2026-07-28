# alles

> ترجمة مراجعة في 21 يوليو 2026 · المصدر المعتمد: `README.md` · مراجعة المصدر:
> `phase10-canonical-2026-07-21`

<div dir="rtl">

[english](../../README.md) · [français](README.fr.md) · [español](README.es.md) ·
[简体中文](README.zh-Hans.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) ·
[한국어](README.ko.md) · **العربية**

**alles** تطبيق شخصي تستضيفه بنفسك. يجمع برنامج Python واحد Aide والبحث والبريد والمستندات المترابطة
بصيغة Markdown واليوميات والملفات والتقويم والمهام والشؤون المالية والصور وجهات الاتصال وخزنة مشفرة.
تبقى البيانات المحلية في مجلد تتحكم فيه. لا توجد بيانات قياس عن بعد؛ ولا يتلقى المزوّد الخارجي إلا الطلبات
التي تختار إرسالها إليه.

## بدء سريع

تحتاج إلى Python 3.11 أو إصدار أحدث.

</div>

```bash
git clone https://github.com/jxherc/alles.git
cd alles
pip install -r requirements.lock
python app.py
```

<div dir="rtl">

افتح `http://localhost:6769`. لا تحتاج إلى مفتاح API لبدء التشغيل. أضف نموذجاً من
**الإعدادات ← النماذج** فقط عندما تريد استخدام Aide.

للتثبيت المُدار على macOS/Linux شغّل `./alles install`. يجهز `alles update` الإصدار الجديد ويتحقق من
سلامته، ويعيد `alles update rollback` زوج الشفرة والبيانات السابق. يحتفظ `./alles uninstall` بالبيانات
الشخصية.

Docker:

</div>

```bash
docker build -t alles .
docker run -p 127.0.0.1:6769:6769 -v alles-data:/app/data alles
```

<div dir="rtl">

قصر المنفذ على عنوان الجهاز المحلي يبقي الحاوية الجديدة متاحة من هذا الجهاز فقط.

## البيانات والشبكة والنسخ الاحتياطية

صُمم Alles لمستخدم واحد. قبل إتاحة الوصول عبر الشبكة، فعّل المصادقة واختر كلمة مرور قوية للمالك واضبط
`secret_key` حقيقية. اقرأ [قسم الأمان](../../specifications.md#security--read-before-exposing-it) قبل
إتاحة الخدمة للآخرين.

يمكنك من **الإعدادات ← النسخ الاحتياطي** إنشاء نسخة محلية مشفرة أو إرسالها يدوياً إلى WebDAV أو مخزن
متوافق مع S3. احتفظ بمفتاح الاسترداد في مكان منفصل. يجري التحقق من بيانات الاستعادة وتجهيزها قبل تعديل
البيانات العاملة.

## مزيد من المعلومات

توجد القائمة الكاملة للتطبيقات والمسارات والبنية في [`specifications.md`](../../specifications.md).
وتوجد التبعيات وتراخيصها في [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

## الترخيص

MIT. راجع [`LICENSE`](../../LICENSE).

</div>
