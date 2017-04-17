import os
import subprocess

def PrintListWithMsg(msg, l):
  """Prints a list of items with ident and a title message.

  Args:
    msg: str - a title message
    l: List[str] - a list of item to print
  """
  print msg
  for item in l:
    print '  ' + item
  print ""

def GetOutputOfTarget(target):
  """Returns the bazel-bin output of the java_library target.

  Args:
    target: str - the full bazel target name (e.g. //a/b:c)
  Returns:
    str - the bazel-bin path of the output lib<target>.jar file
        (e.g. bazel-bin/a/b/libc.jar)
  """
  # Special case for targets under workspace root
  if target.startswith("//:"):
    return "bazel-bin/lib%s.jar" % target[3:]

  # Remove leading double-slash
  target = target[2:]
  idx = target.rfind(':')
  if idx < 0:
    idx = target.rfind('/')
    target_path = target
  else:
    target_path = target[:idx]
  
  target_name = target[(idx + 1):]
  return "bazel-bin/%s/lib%s.jar" % (target_path, target_name)

def QueryTargets(path):
  """Executes "bazel query <path>" to get list of targets under given path.
  
  Args:
    path: str - see parameter of "bazel query <path>" command
  Returns:
    List[str] - list of bazel target names (e.g. //a/b:c)
  """
  if not path:
    return []
  with open(os.devnull, "w") as fnull:
    process = subprocess.Popen(
        ["bazel", "query", path], 
        stdout=subprocess.PIPE,
        stderr=fnull)
    out = process.stdout.read().strip()
    return out.split('\n') if out else []

def QueryTransitiveDeps(target):
  """Executes bazel query to get all transitive java_library dependencies.

  This method executes bazel query "kind('java_library', deps(<target>))".
  See "deps" and "kind" of bazel query language for details.

  Args:
    target: str - the bazel target name (e.g. //a/b:c)
  Returns:
    List[str] - a list of target names
  """
  if not target:
    return []
  with open(os.devnull, "w") as fnull:
    query_str = "kind('java_library', deps(%s))" % target
    process = subprocess.Popen(
        ["bazel", "query", query_str], 
        stdout=subprocess.PIPE, 
        stderr=fnull)
    out = process.stdout.read().strip()
    return out.split('\n') if out else []

def BuildTargets(targets):
  """Builds given list targets with bazel.
  Args:
    targets: List[str] - list of bazel target names (e.g. //a/b:c)
  """
  PrintListWithMsg("Building dependencies...", targets)
  cmds = ["bazel", "build"] + list(targets)
  status = subprocess.call(cmds)
  if status != 0:
    print "Failed to build dependencies of target path!"
    exit(0)

path = "example/com/tinymake/example/..."
targets = set(QueryTargets(path))
dependencies = set()
for target in targets:
  print "..Analyzing target: " + target
  deps = [dep for dep in QueryTransitiveDeps(target) if dep not in targets]
  dependencies.update(deps)
BuildTargets(dependencies)
for dep in dependencies:
  print GetOutputOfTarget(dep)
