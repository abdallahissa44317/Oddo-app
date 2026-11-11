from datetime import datetime
import io
import json
import xmlrpc.client
import pandas as pd
import streamlit as st

# 1. إعدادات الصفحة
st.set_page_config(
    page_title='تطبيق Odoo POS - التقرير المالي حسب العملات',
    page_icon='📱',
    layout='wide',
    initial_sidebar_state='expanded',
)

# 2. إعدادات الاتصال المدمجة
CONFIG = {
    'url': 'https://navybits-al-amin.odoo.com/',  # ضع هنا رابط سيرفر Odoo
    'db': 'navybits-al-amin-production-16937617',  # ضع هنا اسم قاعدة البيانات
    'accounts': [
        {
            'label': 'abu samraa',
            'username': 'أبو سمرا',
            'password': '1234',
        },
        {
            'label': 'dewar',
            'username': 'الدوار',
            'password': '1234',
        },
    ],
}


def get_config():
  if hasattr(st, 'secrets') and 'url' in st.secrets:
    return {
        'url': st.secrets['url'],
        'db': st.secrets['db'],
        'accounts': json.loads(st.secrets['accounts_json']),
    }
  return CONFIG


cfg = get_config()


# 3. دالة جلب الجلسات وتجميع كل عملة لوحدها بشكل مستقل
def fetch_open_sessions(account):
  try:
    common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
    uid = common.authenticate(
        cfg['db'], account['username'], account['password'], {}
    )
    if not uid:
      return None, None, f"فشل الاتصال بالحساب: {account['label']}"

    models = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")
    domain = [('state', '=', 'opened')]

    sessions = models.execute_kw(
        cfg['db'],
        uid,
        account['password'],
        'pos.session',
        'search_read',
        [domain],
        {
            'fields': [
                'id',
                'name',
                'config_id',
                'user_id',
                'start_at',
                'cash_register_balance_start',
                'total_payments_amount',
            ]
        },
    )
    if not sessions:
      return [], [], None

    session_ids = [s['id'] for s in sessions]
    orders = models.execute_kw(
        cfg['db'],
        uid,
        account['password'],
        'pos.order',
        'search_read',
        [[('session_id', 'in', session_ids)]],
        {'fields': ['id', 'session_id', 'payment_ids']},
    )

    order_to_session = {}
    all_p_ids = []
    for o in orders:
      s_id = o['session_id'][0] if o.get('session_id') else None
      p_ids = o.get('payment_ids', [])
      all_p_ids.extend(p_ids)
      for pid in p_ids:
        order_to_session[pid] = s_id

    # تجميع المبالغ لكل عملة على حدة لكل جلسة بغض النظر عن طريقة الدفع (كاش أو بطاقة)
    session_currency_totals = {s_id: {} for s_id in session_ids}
    all_currencies_set = set()

    if all_p_ids:
      payments = models.execute_kw(
          cfg['db'],
          uid,
          account['password'],
          'pos.payment',
          'search_read',
          [[['id', 'in', all_p_ids]]],
          {'fields': ['id', 'currency_id', 'amount']},
      )
      for p in payments:
        amt = p.get('amount', 0.0)
        s_id = order_to_session.get(p['id'])
        if not s_id:
          continue

        # استخراج اسم العملة فقط لجعل كل عملة مستقلة
        curr_name = (
            p['currency_id'][1] if p.get('currency_id') else 'عملة غير محددة'
        )
        all_currencies_set.add(curr_name)

        if curr_name not in session_currency_totals[s_id]:
          session_currency_totals[s_id][curr_name] = 0.0
        session_currency_totals[s_id][curr_name] += amt

    data = []
    for s in sessions:
      s_id = s['id']
      row = {
          'رمز الجلسة': s.get('name'),
          'الفرع': s['config_id'][1] if s.get('config_id') else 'غير محدد',
          'الكاشير': s['user_id'][1] if s.get('user_id') else 'غير محدد',
          'تاريخ الفتح': s.get('start_at'),
          'الافتتاحي كاش': s.get('cash_register_balance_start', 0.0),
      }

      # إضافة عمود مستقل لكل عملة لتظهر لوحدها تماماً
      for curr in all_currencies_set:
        row[f'إجمالي {curr}'] = session_currency_totals[s_id].get(curr, 0.0)

      data.append(row)

    return data, list(all_currencies_set), None
  except Exception as e:
    return None, None, str(e)


# 4. واجهة المستخدم Web UI
st.title('📱POS')

st.sidebar.header('⚙️ الخيارات')
accounts = cfg.get('accounts', [])
acc_labels = ['جميع الفروع'] + [a['label'] for a in accounts]
selected_branch = st.sidebar.selectbox('اختر الفرع:', acc_labels)

if st.sidebar.button('🔄 تحديث البيانات'):
  st.rerun()

target_accounts = (
    accounts
    if selected_branch == 'جميع الفروع'
    else [a for a in accounts if a['label'] == selected_branch]
)

all_data = []
all_currencies_union = set()
errors = []

with st.spinner('جاري جلب البيانات وفصل العملات من سيرفر Odoo...'):
  for acc in target_accounts:
    res, currencies, err = fetch_open_sessions(acc)
    if err:
      errors.append(err)
    elif res:
      all_data.extend(res)
      if currencies:
      # تأكيد تحديث مجموعة العملات الشاملة
        all_currencies_union.update(currencies)

if errors and not all_data:
  st.error('❌ ' + '\n'.join(errors))
elif not all_data:
  st.warning('⚠️ لا توجد جلسات مفتوحة حالياً لهذا الاختيار.')
else:
  df = pd.DataFrame(all_data)

  st.success(f'✨ تم بنجاح عرض البيانات مفصولة حسب العملات لـ {len(df)} جلسة.')
  st.divider()

  # عرض بطاقات إحصائية مستقلة لكل عملة في أعلى الصفحة
  st.subheader('📊 إجمالي التحصيلات لكل عملة على حدة')
  if all_currencies_union:
    cols = st.columns(len(all_currencies_union))
    for i, curr in enumerate(all_currencies_union):
      col_key = f'إجمالي {curr}'
      if col_key in df.columns:
        total_curr = df[col_key].sum()
        with cols[i]:
          st.metric(label=f'إجمالي {curr}', value=f'{total_curr:,.2f}')

  st.divider()

  st.subheader('📌 جدول الجلسات (كل عملة في عمود مستقل)')
  st.dataframe(df, use_container_width=True)

  # زر تحميل ملف Excel مفصل حسب العملات
  buffer = io.BytesIO()
  with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name='Currencies Report')

  st.download_button(
      label='📥 تنزيل ملف Excel مفصل حسب العملات',
      data=buffer.getvalue(),
      file_name=(
          f"Odoo_Currencies_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
      ),
      mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  )
