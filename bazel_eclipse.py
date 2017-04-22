import os
import re
import shutil
import subprocess
import xml.dom.minidom as minidom
import xml.etree.ElementTree as ET

from optparse import OptionParser

PARSER = OptionParser()
# Required arguments
PARSER.add_option(
    "-n", "--name",
    dest="name", action="store", type="string",
    help="name of the generated eclipse project",
)
PARSER.add_option(
    "-p", "--paths",
    dest="paths", action="append", type="string", 
    help="paths to link as source to the eclipse project",
)

# Optional arguments
PARSER.add_option(
    "-o", "--output_dir",
    dest="output_dir", action="store", type="string",
    default="",
    help=("output directory of the generated eclipse project; by default "
          "this will be set to <workspace_root>/bazel-eclipse/<project_name>"),
)
PARSER.add_option(
    "--sshfs_mount_dir",
    dest="sshfs_mount_dir", action="store", type="string",
    default="",
    help=("if using SSHFS, set the absolute path where the workspace root is "
          "mounted, so that the dependent jars will be copied under the "
          "project and linked sources and dependent libraries will use path "
          "mounted on the client; will void --output_dir if this is set"),
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
  """Executes "bazel query <path>/..." to get list of targets under given path.
  
  Args:
    path: str - a valid directory path
  Returns:
    List[str] - list of bazel targets (e.g. //a/b:c)
  """
  path = path.rstrip("/") + "/..."
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


def GetAbsolutePath(path):
  return os.path.abspath(os.path.expanduser(path))


class EclipseProjectGenerator(object):
  def __init__(self, name, src_paths):
    """Constructs instance with minimum required args.

    Args:
      name: str - name of the eclipse project
      src_paths: List[str] - paths for the source files
    """
    # Eclipse project info
    self.name_ = name
    self.src_paths_ = src_paths

    # Bazel workspace info
    self.workspace_root_ = GetWorkspaceRoot()

    # Output directory
    if OPTIONS.output_dir and not OPTIONS.sshfs_mount_dir:
      self.project_base_ = GetAbsolutePath(os.path.join(output_dir, name))
    else:
      self.project_base_ = os.path.join(
          self.workspace_root_, "bazel-eclipse", name)
    MakeDirsIfNotExists(self.project_base_)

    # Project directory structure
    self.project_bazel_deps_ = os.path.join(
        self.project_base_, "lib", OPTIONS.bazel_output_name)
    self.project_config_ = os.path.join(self.project_base_, ".project")
    self.project_clspath_ = os.path.join(self.project_base_, ".classpath")
    self.project_settings_ = os.path.join(self.project_base_, ".settings")
    self.project_settings_file_ = os.path.join(
        self.project_settings_, "org.eclipse.jdt.core.prefs")

    # Source paths grouped by top level dir name
    self.grouped_rel_src_paths_ = self.GroupSourcePaths_()

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

    self.UpdateProjectConfig_()
    self.UpdateProjectClspath_(jar_paths)
    self.UpdateProjectSettings_()

  def UpdateProjectConfig_(self):
    # Root element - projectDescription
    root = None
    if os.path.exists(self.project_config_):
      root = ET.parse(self.project_config_).getroot()
    else:
      root = ET.Element('projectDescription')

    self.GetChildXmlElement_(root, "name").text = self.name_
    self.CreateChildXmlElement_(root, "comment")
    self.CreateChildXmlElement_(root, "projects")

    # Default build spec
    build_spec = self.CreateChildXmlElement_(root, "buildSpec")
    if build_spec is not None:
      build_cmd = self.GetChildXmlElement_(build_spec, 'buildCommand')
      self.GetChildXmlElement_(build_cmd, 'name').text = (
          "org.eclipse.jdt.core.javabuilder")
      self.CreateChildXmlElement_(build_cmd, 'arguments')

    # Default natures
    natures = self.CreateChildXmlElement_(root, "natures")
    if natures is not None:
      self.GetChildXmlElement_(natures, 'nature').text = (
          "org.eclipse.jdt.core.javanature")

    # Liked sources
    if root.find("linkedResources") is not None:
      for res in root.findall("linkedResources"):
        root.remove(res)
    res = self.CreateChildXmlElement_(root, "linkedResources")
    for name in self.grouped_rel_src_paths_.keys():
      # Construct path either on SSHFS host or client machine
      path = None
      if OPTIONS.sshfs_mount_dir:
        path = os.path.join(OPTIONS.sshfs_mount_dir, name)
      else:
        path = os.path.join(self.workspace_root_, name)
      link = self.GetChildXmlElement_(res, "link")
      self.GetChildXmlElement_(link, "name").text = name
      self.GetChildXmlElement_(link, "type").text = "2"
      self.GetChildXmlElement_(link, "location").text = path

    # Write to file
    result_str = ET.tostring(root)
    reparsed = minidom.parseString(result_str)
    reparsed_str = reparsed.toprettyxml(indent="  ").replace("\n\n", "\n")
    f = open(self.project_config_, 'w+')
    f.write(reparsed_str)

  def UpdateProjectClspath_(self, jar_paths):
    root = ET.Element("classpath")  

    # Source filters
    for name, paths in self.grouped_rel_src_paths_.items():
      for path in paths:
        entry = ET.SubElement(root, "classpathentry")
        entry.set("including", os.path.join(path, "**/*"))
        entry.set("kind", "src")
        entry.set("path", name)

    # Eclipse default
    entry = ET.SubElement(root, "classpathentry")
    entry.set("kind", "con")
    entry.set("path",
        "org.eclipse.jdt.launching.JRE_CONTAINER/"
        "org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/"
        "JavaSE-1.8")

    # Output
    entry = ET.SubElement(root, "classpathentry")
    entry.set("kind", "output")
    entry.set("path", "bin")

    # Dependencies
    for jar_path in jar_paths:
      # Path either on SSHFS host or client machine
      if OPTIONS.sshfs_mount_dir:
        jar_path = jar_path.replace(
            self.workspace_root_, OPTIONS.sshfs_mount_dir)
      entry = ET.SubElement(root, "classpathentry")
      entry.set("kind", "lib")
      entry.set("path", jar_path)
    PrintListWithMsg("Linked the following dependencies:", jar_paths)

    # Write file
    result_str = ET.tostring(root)
    reparsed = minidom.parseString(result_str)
    reparsed_str = reparsed.toprettyxml(indent="  ").replace("\n\n", "\n")
    f = open(self.project_clspath_, 'w+')
    f.write(reparsed_str)

  def UpdateProjectSettings_(self):
    # Eclipse default
    settings = [
        "eclipse.preferences.version=1",
        "org.eclipse.jdt.core.compiler.codegen.inlineJsrBytecode=enabled",
        "org.eclipse.jdt.core.compiler.codegen.targetPlatform=1.8",
        "org.eclipse.jdt.core.compiler.codegen.unusedLocal=preserve",
        "org.eclipse.jdt.core.compiler.compliance=1.8",
        "org.eclipse.jdt.core.compiler.debug.lineNumber=generate",
        "org.eclipse.jdt.core.compiler.debug.localVariable=generate",
        "org.eclipse.jdt.core.compiler.debug.sourceFile=generate",
        "org.eclipse.jdt.core.compiler.problem.assertIdentifier=error",
        "org.eclipse.jdt.core.compiler.problem.enumIdentifier=error",
        "org.eclipse.jdt.core.compiler.source=1.8",
    ]
    MakeDirsIfNotExists(self.project_settings_)
    f = open(self.project_settings_file_, "w+")
    f.write("\n".join(settings))

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
    if not OPTIONS.sshfs_mount_dir:
      return file_path
    else:
      dest_dir = os.path.expanduser(
          os.path.join(self.project_bazel_deps_, target_path))
      dest_file_path = os.path.join(dest_dir, file_name)
      MakeDirsIfNotExists(dest_dir)
      shutil.copy(file_path, dest_file_path)
      return dest_file_path

  def GroupSourcePaths_(self):
    results = {}
    for src_path in self.src_paths_:
      # Absolute path
      abs_path = GetAbsolutePath(src_path)
      assert abs_path.startswith(self.workspace_root_)

      # Name (top level dir name)
      workspace_path = abs_path[len(self.workspace_root_):].lstrip("/")
      m = re.search("^([^:/]+)", workspace_path)
      name = m.group(1) if m.group(1) else "src"
      # Path relative to <workspace_root>/<name>/
      rel_path = workspace_path[len(name):].lstrip("/")
      results.setdefault(name, []).append(rel_path)
    return results

  def CreateChildXmlElement_(self, parent, child_name):
    child = parent.find(child_name)
    return None if child is not None else ET.SubElement(parent, child_name)

  def GetChildXmlElement_(self, parent, child_name):
    child = parent.find(child_name)
    return child if child is not None else ET.SubElement(parent, child_name)


def main():
  generator = EclipseProjectGenerator(OPTIONS.name, OPTIONS.paths)
  generator.Update()


if __name__ == "__main__":
    main()
