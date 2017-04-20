import os
import re
import shutil
import subprocess

from optparse import OptionParser

PARSER = OptionParser()
# Required arguments
PARSER.add_option(
    "-n", "--name",
    dest="name", action="store", type="string",
    help="name of the generated eclipse project",
)
PARSER.add_option(
    "-o", "--output_dir",
    dest="output_dir", action="store", type="string",
    help="output directory of the generated eclipse project", 
)
PARSER.add_option(
    "-p", "--paths",
    dest="paths", action="append", type="string", 
    help="paths to link as source to the eclipse project",
)

# Optional arguments
PARSER.add_option(
    "--copy", 
    dest="copy", action="store_true",
    default=False,
    help=("if set, it will copy output jar of transitive dependencies to the "
          "eclipse project directory; useful when using with SSHFS"),
)
PARSER.add_option(
    "--bazel_binary", 
    dest="bazel_binary", action="store", type="string",
    default="bazel",
    help="path or command to the bazel binary",
)
PARSER.add_option(
    "--bazel_output_name",
    dest="bazel_output_name", action="store", type="string",
    default="bazel-bin",
    help="name of the bazel output directory (default: bazel-bin)",
)
OPTIONS = PARSER.parse_args()[0]


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


def MakeDirsIfNotExists(path):
  if not os.path.exists(path):
    os.makedirs(path)


def RmDirsIfExists(path):
  def handler(func, path, excinfo):
    print "[WARN] Failed to clean up %s" % path
  if os.path.exists(path):
    shutil.rmtree(path, ignore_errors=True, onerror=handler)


def ParseTarget(target):
  """Returns target path relative to the workspace root and target name.

  Arg:
    target: str - the bazel target (e.g. //a/b:c)
  Returns:
    Tuple[str, str] - the target path and name, or None if target is invalid
  """
  m = re.search("^//([^:]+)?:?([^/:]+)?$", target)
  if not m:
    return None
  target_path = m.group(1)
  target_name = m.group(2) if m.group(2) else os.path.basename(target_path)
  if not target_name or os.path.isabs(target_path):
    return None
  return (target_path, target_name)

def QueryTargets(path):
  """Executes "bazel query <path>" to get list of targets under given path.
  
  Args:
    path: str - see parameter of "bazel query <path>" command
  Returns:
    List[str] - list of bazel targets (e.g. //a/b:c)
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
    target: str - the bazel target (e.g. //a/b:c)
  Returns:
    List[str] - a list of targets
  """
  if not target:
    return []
  print "..Analyzing target: " + target
  with open(os.devnull, "w") as fnull:
    query_str = "kind('java_library', deps(%s))" % target
    process = subprocess.Popen(
        ["bazel", "query", query_str], 
        stdout=subprocess.PIPE, 
        stderr=fnull)
    out = process.stdout.read().strip()
    return out.split('\n') if out else []


def BuildTargets(targets):
  """Builds targets with bazel.

  Args:
    targets: List[str] - list of bazel targets (e.g. //a/b:c)
  """
  PrintListWithMsg("Building dependencies...", targets)
  cmds = [OPTIONS.bazel_binary, "build"] + list(targets)
  status = subprocess.call(cmds)
  if status != 0:
    print "Failed to build dependencies of target path!"
    exit(0)


def GetWorkspaceRoot():
  """Returns root of the bazel workspace."""
  with open(os.devnull, "w") as fnull:
    process = subprocess.Popen(
        [OPTIONS.bazel_binary, "info"], stdout=subprocess.PIPE,  stderr=fnull)
    out = process.stdout.read().strip()
    lines = out.split('\n')
    workspace_root = None
    title = "workspace: "
    for line in lines:
      if line.startswith(title):
        workspace_root = line[len(title):]
    if not workspace_root:
      print "only supported from within a workspace."
      exit(0)
    return workspace_root


class EclipseProjectGenerator(object):
  def __init__(self, name, output_dir, src_paths):
    """Constructs instance with minimum required args.

    Args:
      name: str - name of the eclipse project
      output_dir: str - base path that the project folder will be generated
      src_paths: List[str] - paths for the source files
    """
    # Eclipse project info
    self.project_base_ = os.path.expanduser(os.path.join(output_dir, name))
    self.project_bazel_deps_ = os.path.join(
        self.project_base_, "lib", OPTIONS.bazel_output_name)
    self.project_config_ = os.path.join(self.project_base_, ".project")
    self.project_clspath_ = os.path.join(self.project_base_, ".classpath")
    self.project_settings_ = os.path.join(self.project_base_, ".settings")

    # Bazel workspace info
    self.workspace_root_ = GetWorkspaceRoot()
    self.src_paths_ = src_paths

  def Update(self):
    MakeDirsIfNotExists(self.project_base_)
    RmDirsIfExists(self.project_bazel_deps_)

    # Targets under the source folders
    targets = set()
    for path in self.src_paths_:
      targets.update(QueryTargets(path))

    # Transitive deps of the source folders
    transitive_deps = set()
    for target in targets:
      for dep in QueryTransitiveDeps(target):
        if dep not in targets:
          transitive_deps.add(dep)

    # Builds the targets and copies the output
    BuildTargets(list(transitive_deps))
    jar_paths = [self.ProcessBazelOutputJar_(target) 
                 for target in transitive_deps]
    print "\n".join(jar_paths)

    self.UpdateProjectConfig_()
    self.UpdateProjectClspath_(jar_paths)
    self.UpdateProjectSettings_()

  def UpdateProjectConfig_(self):
    pass

  def UpdateProjectClspath_(self, jar_paths):
    pass

  def UpdateProjectSettings_(self):
    pass

  def ProcessBazelOutputJar_(self, target):
    """Processes bazel output jar for the target and returns the absolute path.

    Must be called after building the target. If --copy is set, it will copy
    the output to eclispse project directory.

    Args:
      target: str - the bazel target (e.g. //a/b:c)
    Returns:
      str - the absolute path of the built jar
    """
    (target_path, target_name) = ParseTarget(target)
    file_name = "lib%s.jar" % target_name
    file_path = os.path.expanduser(
        os.path.join(
            self.workspace_root_,
            OPTIONS.bazel_output_name, 
            target_path, 
            file_name))
    if not OPTIONS.copy:
      return file_path
    else:
      dest_dir = os.path.expanduser(
          os.path.join(self.project_bazel_deps_, target_path))
      dest_file_path = os.path.join(dest_dir, file_name)
      MakeDirsIfNotExists(dest_dir)
      shutil.copy(file_path, dest_file_path)
      return dest_file_path

def main():
  path = "example/com/tinymake/example/..."
  generator = EclipseProjectGenerator("Example", "~/", [path])
  generator.Update()

if __name__ == "__main__":
    main()
