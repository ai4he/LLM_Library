import re
import sys
import json
import time
import openai
import argparse
from flask import Flask, render_template, request

def get_stop_tokens():
  keys = list(state_metadata['states'].keys())
  stop_tokens = []
  for i in range(len(keys)-1):
    if state_metadata['states'][keys[i]]['direction'] == 'output' and state_metadata['states'][keys[i+1]]['direction'] == 'input':
      stop_tokens.append(keys[i+1])
  return stop_tokens

def get_finish_tokens():
  keys = list(state_metadata['states'].keys())
  return [keys[-1]]

def get_decision_tokens():
  return [key for key in state_metadata['states'] if state_metadata['states'][key]['direction'] == 'loop']

def get_session(role_id=None):
  if role_id not in sessions:
    session_id = create_session(role_id)
    session = sessions[session_id]
    session['messages'].append({"role": "system", "content": system_msg})
    return session_id
  else:
    return role_id

def create_session(session_id):
  session_id = str(int(time.time()))
  session = sessions[session_id] = {}
  session['iterations'] = 0
  session['messages'] = []
  session[input_var] = []
  session['initial'] = True
  session['finished'] = False
  return session_id

def finish_process(session_id):
  global sessions
  session = sessions[session_id]
  if session['finished']:
    return True
  if session['initial']:
    return False
  return False

def chat_completion(session_id, query, stop_tokens, track_tokens_arr):
  global sessions
  session = sessions[session_id]
  print('')
  found_token = False
  max_length = 0
  for token in track_tokens_arr:
    if len(token) > max_length:
      max_length = len(token)

  session['messages'].append({"role": "user", "content": query})

  # print(session['messages'])

  has_finished = False
  attempts = 0
  max_attempts = 10
  wait_attempt = 3
  reply = ''
  stopped_by_token = ''
  while not has_finished and attempts < max_attempts:
    try:
      print('API_REQUEST: ',session['messages'])
      response = openai.ChatCompletion.create(
        model=openai_model,
        messages=session['messages'],
        stream=True
        # stop=stop_tokens
      )

      for stream_resp in response:
        if 'content' in stream_resp["choices"][0]['delta']:
          token = stream_resp["choices"][0]["delta"]["content"]
          reply += token
          window = reply[-1*(max_length+1):]
          # print(token)
          sys.stdout.write(token)
          for finish_token in finish_tokens:
            if finish_token in window:
              stopped_by_token = finish_token
              session['finished'] = True
          for stop_token in stop_tokens:
            if stop_token in window:
              found_token = True
              stopped_by_token = stop_token
              response.close()
              break
      has_finished = True
    except Exception as e:
      print(e)
      time.sleep(wait_attempt)
    attempts += 1

  # reply = response["choices"][0]["message"]["content"]
  session['last_reply'] = reply
  return {'reply': reply, 'stop': stopped_by_token}

def parse_text(text):
  sections = re.split(r'\n(?=[A-Z_]+:)', text)
  result = {}
  for section in sections:
    if ':' in section:
      title, content = section.split(':', 1)
      result[title.strip()] = content.strip()
    else:
      result['NO_SECTION'] = section.strip()
  return result

def process(session_id):
  global sessions
  session = sessions[session_id]
  result = {}
  variables = session[input_var][-1]
  sections = process_input(session_id, variables)
  for section in sections:
    result[section] = sections[section]
  return result

def extract_json(text_field):
  json_pattern = r'(\[\s*{.*}\s*\])|({\s*".*":\s*".*".*})'
  json_string = re.search(json_pattern, text_field, re.DOTALL)
  try:
    if json_string:
      return json.loads(json_string.group())
    else:
      json_string = re.search(json_pattern, '{' + text_field, re.DOTALL)
      if json_string:
        return json.loads(json_string.group())
      else:
        json_string = re.search(json_pattern, '{' + text_field + '}', re.DOTALL)
        if json_string:
          return json.loads(json_string.group())
        else:
          json_string = re.search(json_pattern, '[' + text_field, re.DOTALL)
          if json_string:
            return json.loads(json_string.group())
          else:
            json_string = re.search(json_pattern, '[' + text_field + ']', re.DOTALL)
            if json_string:
              return json.loads(json_string.group())
  except:
    return {}
  return {}

def get_dict(json_string):
  return extract_json(json_string)

def get_default_value(key):
  step_metadata = state_metadata['states'][key]
  if step_metadata['type'] == 'object':
    return '{'
  elif step_metadata['type'] == 'array':
    return '['
  return ''

def form_query(key):
  key_value = key.replace(':','')
  if key_value in state_metadata['states']:
    step_metadata = state_metadata['states'][key_value]
    if step_metadata['type'] == 'object':
      return f'{key}: ' + '{'
    elif step_metadata['type'] == 'array':
      return f'{key}: ' + '['
    return f'{key}: '
  else:
    return f'{key}'

def process_input(session_id, input_dict):
  global sessions
  session = sessions[session_id]
  enforce = False
  query = ''
  skip_next = False
  last_requested_step = ''
  comma = ''
  for key in input_dict:
    if enforce == False:
      output_state = key
      # step_metadata = state_metadata['states'][key.replace(':','')]
      if input_dict[key] == True:
        query += comma + form_query(key)
        skip_next = True
        comma = '\n'
      else:
        if not skip_next:
          if input_dict[key] == '':
            query += comma + form_query(key)
          else:
            query += comma + f'{key}: {input_dict[key]}'
          comma = '\n'
    if input_dict[key] == '' or input_dict[key] == True:
      if enforce == False:
        enforce = []
      else:
        enforce.append(key)

  # session['messages'].append({"role": "user", "content": query})
  # print(output_state)
  reply_obj = chat_completion(session_id, query, stop_tokens, track_tokens_arr)
  reply = reply_obj['reply']
  stopped_by_token = reply_obj['stop']
  session['messages'].append({"role": "assistant", "content": reply})
  json.dump(session['messages'], open(f'data/start/{session_id}.json','w'))
  # print('\nDEBUG',input_dict,output_state)
  reply = f'{output_state}: ' + reply
  sections = parse_text(reply)
  # if 'NO_SECTION' in sections:
  #   query_states = parse_text(query)
  #   query_keys = list(query_states.keys())
  #   if len(query_states[query_keys[-1]]) < 2:
  #     sections[query_keys[-1]] = sections['NO_SECTION']
  #     del sections['NO_SECTION']
  # print(sections)
  enforce_chain = {}
  if enforce:
    counter = 0
    for enf in enforce:
      if enf not in reply:
        if counter == 0:
          enforce_chain[enf] = True
        else:
          enforce_chain[enf] = ''
        counter += 1
  if len(enforce_chain.keys()) > 0:
    reply_obj = process_input(session_id, enforce_chain)
    sections_enf = reply_obj['sections']
    stopped_by_token = reply_obj['stop']
    for section in sections_enf:
      sections[section] = sections_enf[section]
  return {'sections': sections, 'stop': stopped_by_token}

def run(session_id, variables):
  global sessions
  session = sessions[session_id]
  if not finish_process(session_id):
    session[input_var].append(variables)
    output = process(session_id)
    output[session_var] = session_id
    output['status'] = 'ACTIVE'
    return output
  else:
    output = {}
    output[session_var] = session_id
    output['status'] = 'FINISHED'
    return output

def has_finished(session_id):
  if session_id:
    return finish_process(session_id)
  return False


def endpoint(session_id, variables):
  if not session_id:
    session_id = get_session()
  return run(session_id, variables)

def get_next_step_name(state):
  state_keys = list(state_metadata['states'].keys())
  num_states = len(state_keys)
  if state in state_keys:
    index = state_keys.index(state)
    if (index+1) < num_states:
      return state_keys[index + 1]
  return None

def get_next_step(state):
  next_state_name = get_next_step_name(state)
  if next_state_name is not None:
    return next_state_name, state_metadata['states'][next_state_name]
  return None, None

def is_state_not_terminal(state):
  next_state_name, next_state  = get_next_step(state)
  if next_state is not None:
    if next_state['direction'] != 'input':
      return True
  return False

def get_special_cases(state, last_key, last_value):
  intervene = False
  variables = {}
  if last_key in decision_tokens:
    if last_value == '':
      intervene = True
      variables = {':':''}
    elif any(element in last_value for element in finish_tokens):
      state = 'finish'
    else:
      json_obj = get_dict(last_value)
      # print(json_obj)
      if next_step in json_obj:
        intervene = True
        variables = {f'{json_obj[next_step]}': ''}
  elif last_key in state_metadata['states'] and 'skip' in state_metadata['states'][last_key] and 'jump' in state_metadata['states'][last_key]['skip']:
    intervene = True
    variables = {'\n':''}
  elif is_state_not_terminal(last_key):
    # print(last_key)
    next_step_name, next_step_metadata = get_next_step(last_key)
    # print(next_step_name)
    intervene = True
    variables = {f'{next_step_name}': get_default_value(next_step_name)}
  return state, intervene, variables

def get_current_state(output, current_state):
  keys = list(state_metadata['states'].keys())
  section_keys = list(output['sections'].keys())
  last_key = section_keys[-1]
  if last_key in keys:
    index = keys.index(last_key)
    if index < (len(keys) - 1):
      return state_metadata['states'][keys[index+1]]['state']
  return current_state

def get_next_state(output, current_state):
  section_keys = list(output['sections'].keys())
  system_keys = list(system_states.keys())
  last_key = section_keys[-1]
  last_value = output['sections'][last_key]
  state = current_state
  while len(system_keys) > 0:
    key = system_keys.pop()
    system_state = system_states[key]
    state_keys = list(system_state['variables'].keys()) + system_state['pre_steps']
    if any(element in section_keys for element in state_keys):
      state = key
      break
  state, intervene, intervene_variables = get_special_cases(state, last_key, last_value)
  return {'state': state, 'intervene': intervene, 'variables': intervene_variables}

def get_system_prompt():
  prompt = f"{state_metadata['context']}\n\n"
  keys = list(state_metadata['states'].keys())
  for i, key in enumerate(state_metadata['states']):
    prompt_text = f"{key}: {state_metadata['states'][key]['system']}"
    if state_metadata['states'][key]['type'] in ['object', 'array']:
      if 'json' in state_metadata['states'][key]:
        prompt_vars = 'The JSON object contains the following keys: '
        prompt_objs = ''
        comma = ''
        for json_key in state_metadata['states'][key]['json']:
          json_value = state_metadata['states'][key]['json'][json_key]
          if isinstance(json_value, list):
            prompt_vars += comma + f"{json_key} ({json_value[0]}, {json_value[1]})"
          if isinstance(json_value, dict):
            prompt_obj = f"The {json_key} object contains the following keys: "
            comma_dict = ''
            for obj_key in state_metadata['states'][key]['json'][json_key]:
              obj_value = state_metadata['states'][key]['json'][json_key][obj_key]
              prompt_obj += comma_dict + f"{obj_key} ({obj_value[0]}, {obj_value[1]})"
              comma_dict = ', '
            prompt_obj += '. '
            prompt_objs += prompt_obj
          comma = ', '
        prompt_vars += '. '
        prompt_text += prompt_vars + prompt_objs
    if i < (len(keys)-1):
      if state_metadata['states'][key]['direction'] == 'output' and state_metadata['states'][keys[i+1]]['direction'] in ['output', 
'loop', 'end']:
        if not ('skip' in state_metadata['states'][key] and 'jump' in state_metadata['states'][key]['skip']):
          prompt_text += f" Then go to {keys[i+1]}."
    prompt_text += "\n"
    prompt += prompt_text
  prompt += "\nBegin!\n\n"
  return prompt

def get_prompt():
  prompt = get_system_prompt()
  comma = ''
  for key in state_metadata['states']:
    prompt += comma + f"{key}: {state_metadata['states'][key]['user']}"
    comma = '\n'
    if state_metadata['states'][key]['user'] == '':
      break
  return prompt

def get_system_states():
  system_states = {}
  pre_steps = []
  is_first_state = True
  before_input = True
  keys = list(state_metadata['states'].keys())
  first_state = state_metadata['states'][keys[0]]['state']
  system_states[first_state] = {
      'variables': {},
      'pre_steps': []
  }
  for key in state_metadata['states']:
    state = state_metadata['states'][key]['state']
    if state not in system_states:
      system_states[state] = {
          'variables': {},
          'pre_steps': []
      }
      if is_first_state:
        system_states[state]['pre_steps'] = pre_steps
      is_first_state = False
      before_input = True
    if is_first_state:
      system_states[state]['variables'][key] = state_metadata['states'][key]['user']
      if state_metadata['states'][key]['user'] == '':
        pre_steps.append(key)
    else:
      if before_input and state_metadata['states'][key]['direction'] == 'output':
        system_states[state]['pre_steps'].append(key)
      elif (before_input and state_metadata['states'][key]['direction'] == 'input') or not before_input:
        system_states[state]['variables'][key] = state_metadata['states'][key]['user']
        before_input = False
      else:
        system_states[state]['variables'][key] = state_metadata['states'][key]['user']

  return system_states

def set_input_variables(variables, input_vars):
  variables = variables.copy()
  if input_var in input_vars:
    value = input_vars[input_var]
    for key in variables:
      if variables[key] == '' and key in state_metadata['states'] and state_metadata['states'][key]['direction'] == 'input':
        variables[key] = value
  return variables

def format_output(output):
  for key in output['sections']:
    if key in state_metadata['states'] and state_metadata['states'][key]["type"] in ['object', 'array']:
      casted_obj = get_dict(output['sections'][key])
      if len(casted_obj) > 0:
        output['sections'][key] = casted_obj
  return output

preset = 'start.json'

prompt_file = preset
# openai_model = "gpt-3.5-turbo-16k"
# openai_model = "gpt-3.5-turbo"
openai_model = "gpt-4"
# openai_model = "gpt-4-0314"
sessions = {}
max_iterations = 2

state_metadata = json.load(open(prompt_file, 'r'))

session_var = 'session_id'
input_var = 'input_val'
next_step = 'next_step'

stop_tokens = get_stop_tokens()
finish_tokens = get_finish_tokens()
decision_tokens = get_decision_tokens()
track_tokens_arr = stop_tokens + finish_tokens
system_states = get_system_states()
system_msg = get_system_prompt()

web_type = 'server'
port = 5007

app = Flask(__name__, template_folder='static', static_folder='static')

@app.route('/', methods=['GET', 'POST'])
def index():
  if request.method == 'GET':
    page = request.args.get('page', default='index.html')
    return render_template(page)
  else:
    session_id = ''
    if session_var in request.form:
      session_id = request.form[session_var]
    if session_id == '':
      current_state = 'init'
    else:
      current_state = sessions[session_id]['current_state']
    variables = system_states[current_state]['variables']
    # print(request.form.to_dict())
    variables = set_input_variables(variables, request.form)
    finish_loop = False
    results = None
    while not finish_loop and not has_finished(session_id):
      output = endpoint(session_id, variables)
      # output = format_output(output)
      if results is None:
        results = output.copy()
      else:
        for param in output:
          if param == 'sections':
            for section in output['sections']:
              results['sections'][section] = output['sections'][section]
          else:
            results[param] = output[param]
      session_id = output[session_var]
      reply_obj = get_next_state(output, current_state)
      if reply_obj['intervene']:
        variables = reply_obj['variables']
      else:
        finish_loop = True
    sessions[session_id]['current_state'] = get_current_state(output, current_state)
    output['current_state'] = sessions[session_id]['current_state']
    output = format_output(output)
    return results

if __name__ == "__main__":
  app.run(port=port, host='0.0.0.0')
