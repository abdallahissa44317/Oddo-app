from datetime import datetime
import io
import json
import xmlrpc.client
import pandas as pd
import streamlit as st

# 1. إعدادات الصفحة
st.set_page_config(
    page_title='Odoo POS - استعراض الجلسات والعملات',
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


# 3. دالة جلب جميع الجلسات (المفتوحة والمغلقة)
def fetch_all_sessions(account):
  try:
    common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
    uid = common.authenticate(
        cfg['db'], account['username'], account['password'], {}
    )
    if not uid:
      return None, f"فشل الاتصال بالحساب: {account['label']}"

    models = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")

    # جلب آخر 50 جلسة من دون شروط على الحالة (تشمل المفتوحة والمغلقة وقيد الإغلاق)
    sessions = models.execute_kw(
        cfg['db'],
        uid,
        account['password'],
        'pos.session',
        'search_read',
        [[]],  # بدون شروط لجلب الكل
        {
            'fields': [
                'id',
                'name',
                'config_id',
                'user_id',
                'start_at',
                'stop_at',
                'state',
                'cash_register_balance_start',
                'total_payments_amount',
            ],
            'limit': 50,  # آخر 50 جلسة لتسريع التصفح
            'order': 'id desc',
        },
    )
    return sessions, None
  except Exception as e:
    return None, str(e)


# 4. دالة جلب تفاصيل جلسة محددة مع فصل العملات
def fetch_session_details(account, session_id):
  try:
    common = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/common")
    uid = common.authenticate(
        cfg['db'], account['username'], account['password'], {}
    )
    if not uid:
      return None, 'فشل المصادقة'

    models = xmlrpc.client.ServerProxy(f"{cfg['url']}/xmlrpc/2/object")

    orders = models.execute_kw(
        cfg['db'],
        uid,
        account['password'],
        'pos.order',
        'search_read',
        [[('session_id', '=', session_id)]],
        {'fields': ['id', 'name', 'date_order', 'amount_total', 'payment_ids']},
    )

    if not orders:
      return {'currency_totals': {}, 'payments': []}, None

    order_to_info = {}
    all_p_ids = []
    for o in orders:
      p_ids = o.get('payment_ids', [])
      all_p_ids.extend(p_ids)
      for pid in p_ids:
        order_to_info[pid] = {
            'order_name': o.get('name'),
            'order_date': o.get('date_order'),
        }

    currency_totals = {}
    payment_details = []

    if all_p_ids:
      payments = models.execute_kw(
          cfg['db'],
          uid,
          account['password'],
          'pos.payment',
          'search_read',
          [[['id', 'in', all_p_ids]]],
          {
              'fields': [
                  'id',
                  'payment_method_id',
                  'currency_id',
                  'amount',
                  'payment_date',
              ]
          },
      )
      for p in payments:
        amt = p.get('amount', 0.0)
        pid = p['id']
        m_name = (
            p['payment_method_id'][1]
            if p.get('payment_method_id')
            else 'أخرى'
        )
        curr_name = (
            p['currency_id'][1] if p.get('currency_id') else 'عملة أساسية'
        )

        # تجميع المبلغ حسب العملة بشكل مستقل تماماً
        if curr_name not in currency_totals:
          currency_totals[curr_name] = 0.0
        currency_totals[curr_name] += amt

        info = order_to_info.get(pid, {})
        payment_details.append({
            'رقم الطلب': info.get('order_name', '-'),
            'طريقة الدفع': m_name,
            'العملة': curr_name,
            'المبلغ': amt,
            'تاريخ العملية': p.get('payment_date', ''),
        })

    return {'currency_totals': currency_totals, 'payments': payment_details}, None
  except Exception as e:
    return None, str(e)


# 5. واجهة المستخدم Web UI
st.title('📱 استعراض جميع جلسات POS (مفتوحة ومغلقة)')

st.sidebar.header('⚙️ الخيارات')
accounts = cfg.get('accounts', [])
acc_labels = [a['label'] for a in accounts]
selected_branch_label = st.sidebar.selectbox('اختر الفرع:', acc_labels)
selected_account = next(
    (a for a in accounts if a['label'] == selected_branch_label), accounts[0]
)

if st.sidebar.button('🔄 تحديث القائمة'):
  st.rerun()

with st.spinner('جاري جلب قائمة الجلسات من أودو...'):
  sessions, err = fetch_all_sessions(selected_account)

if err:
  st.error(f'❌ خطأ في الاتصال: {err}')
elif not sessions:
  st.warning('⚠️ لا توجد جلسات مسجلة في هذا الحساب.')
else:
  # تجهيز خيارات قائمة الجلسات مع حالتها
  session_options = {}
  state_map = {
      'opened': 'مفتوحة 🟢',
      'closing_control': 'قيد الإغلاق 🟡',
      'closed': 'مغلقة 🔴',
  }

  for s in sessions:
    s_name = s.get('name', 'بدون اسم')
    s_state = s.get('state', '')
    state_txt = state_map.get(s_state, s_state)
    s_date = s.get('start_at', 'بدون تاريخ')
    label = f'جلسة: {s_name} | الحالة: {state_txt} | البدء: {s_date}'
    session_options[label] = s['id']

  st.divider()
  st.subheader('🔍 اختر الجلسة المطلوب استعراض تفاصيلها:')
  chosen_label = st.selectbox(
      'اختر من القائمة أدناه:', list(session_options.keys())
  )
  chosen_session_id = session_options[chosen_label]

  # جلب وعرض تفاصيل الجلسة المختارة عند النقر أو تلقائياً
  with st.spinner('جاري جلب تفاصيل العمليات والمدفوعات للجلسة...'):
    details, err_det = fetch_session_details(selected_account, chosen_session_id)

  if err_det:
    st.error(f'❌ {err_det}')
  elif details:
    curr_totals = details['currency_totals']
    payments_list = details['payments']

    st.success('✨ تم تحميل تفاصيل الجلسة بنجاح!')
    st.divider()

    # عرض بطاقات الإحصائيات لكل عملة وحدها
    st.subheader('📊 إجمالي المبالغ حسب كل عملة')
    if curr_totals:
      cols = st.columns(len(curr_totals))
      for i, (curr, total) in enumerate(curr_totals.items()):
        with cols[i]:
          st.metric(label=f'إجمالي {curr}', value=f'{total:,.2f}')
    else:
      st.info('ℹ️ لا توجد مدفوعات مسجلة لهذه الجلسة.')

    st.divider()

    # عرض جدول تفاصيل حركات الدفع
    st.subheader('📌 جدول حركات الدفع التفصيلية')
    if payments_list:
      df_payments = pd.DataFrame(payments_list)
      st.dataframe(df_payments, use_container_width=True)

      # زر تحميل تقرير هذه الجلسة كملف Excel
      buffer = io.BytesIO()
      with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_payments.to_excel(
            writer, index=False, sheet_name='Session Details'
        )

      st.download_button(
          label='📥 تنزيل تقرير هذه الجلسة بصيغة Excel',
          data=buffer.getvalue(),
          file_name=f"Session_Report_{chosen_session_id}.xlsx",
          mime=(
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
          ),
      )
    else:
      st.warning('⚠️ لا توجد مدفوعات نقدية أو تفصيلية مرتبطة بهذه الجلسة.')
